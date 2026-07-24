"""Offline-tested Seedance.nz image Provider adapter.

This module is intentionally independent from the Yunwu adapters.  The public
ImageProviderAdapter seam remains fail-closed; production calls are only made
through the validated ImagePanelService orchestration path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import http.client
import json
import os
import struct
import time
from types import MappingProxyType
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

from .adapters import ImageProviderAdapter, ProviderAsset, ProviderInvocation
from .errors import ImagePanelError, ImagePanelErrorCode
from .models import CancellationToken
from .png import deterministic_png


SEEDANCE_NZ_BASE_URL = "https://api.seedance.nz"
SEEDANCE_NZ_IMAGE_SUBMIT_ENDPOINT = f"{SEEDANCE_NZ_BASE_URL}/v1/image/generations"
SEEDANCE_NZ_IMAGE_TASK_ENDPOINT = f"{SEEDANCE_NZ_BASE_URL}/v1/image/generations/{{task_id}}"
SEEDANCE_NZ_DEFAULT_T2I_MODEL = "seedream-v5-pro-t2i"
SEEDANCE_NZ_DEFAULT_I2I_MODEL = "seedream-v5-pro-i2i"
SEEDANCE_NZ_ALLOWED_MODELS = frozenset(
    {SEEDANCE_NZ_DEFAULT_T2I_MODEL, SEEDANCE_NZ_DEFAULT_I2I_MODEL}
)
SEEDANCE_NZ_ALLOWED_ENDPOINTS = frozenset({SEEDANCE_NZ_IMAGE_SUBMIT_ENDPOINT})
MAX_TIMEOUT_SECONDS = 300.0
MAX_IMAGE_BYTES = 33_554_432
MAX_POLL_ATTEMPTS = 120


@dataclass(frozen=True, slots=True)
class SeedanceNzHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class SeedanceNzProviderReceipt:
    endpoint: str
    model_id: str
    task_id: str | None
    http_status: int
    elapsed_ms: int
    provider_network_performed: bool = True
    provider_asset_id: str | None = None
    result_url: str | None = None
    content_type: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    error_body: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "model_id": self.model_id,
            "task_id": self.task_id,
            "http_status": self.http_status,
            "elapsed_ms": self.elapsed_ms,
            "provider_network_performed": self.provider_network_performed,
            "provider_asset_id": self.provider_asset_id,
            "result_url": self.result_url,
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "error_body": self.error_body,
        }


class SeedanceNzTransport(Protocol):
    def post_json(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> SeedanceNzHttpResponse: ...

    def get_json(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> SeedanceNzHttpResponse: ...

    def get_bytes(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> bytes: ...


class SeedanceNzHttpClient:
    """Small HTTPS client with exact Seedance endpoint checks and no redirects."""

    def __init__(
        self,
        *,
        connection_factory: Callable[..., http.client.HTTPSConnection] = http.client.HTTPSConnection,
    ) -> None:
        self._connection_factory = connection_factory

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        allow_download: bool = False,
    ) -> SeedanceNzHttpResponse:
        parsed_endpoint = urlsplit(endpoint)
        allowed = (
            endpoint in SEEDANCE_NZ_ALLOWED_ENDPOINTS
            or endpoint.startswith(SEEDANCE_NZ_BASE_URL + "/v1/image/generations/")
            or (
                allow_download
                and parsed_endpoint.scheme == "https"
                and parsed_endpoint.hostname is not None
                and (
                    parsed_endpoint.hostname == "api.seedance.nz"
                    or parsed_endpoint.hostname.endswith(".seedance.nz")
                )
            )
        )
        if not allowed:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Provider endpoint is not authorized",
                category="authorization",
                details={"endpoint": endpoint},
            )
        parsed = urlsplit(endpoint)
        allowed_host = parsed.hostname == "api.seedance.nz" or (
            allow_download and parsed.hostname is not None and parsed.hostname.endswith(".seedance.nz")
        )
        if parsed.scheme != "https" or not allowed_host:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Provider endpoint is not authorized",
                category="authorization",
            )
        timeout = min(float(timeout_seconds), MAX_TIMEOUT_SECONDS)
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        connection = self._connection_factory(parsed.hostname, port=parsed.port, timeout=timeout)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        started = time.monotonic()
        try:
            connection.request(method, path, body=body, headers=dict(headers))
            response = connection.getresponse()
            response_body = response.read(MAX_IMAGE_BYTES + 1024)
            elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
            return SeedanceNzHttpResponse(
                int(response.status),
                {str(k).lower(): str(v) for k, v in response.getheaders()},
                response_body,
                elapsed_ms,
            )
        except TimeoutError as exc:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_TIMEOUT,
                "Provider request exceeded the configured timeout",
                category="provider",
            ) from exc
        except ImagePanelError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Provider network request failed",
                category="provider",
                details={"cause_type": type(exc).__name__},
            ) from exc
        finally:
            connection.close()

    def post_json(self, endpoint, *, headers, payload, timeout_seconds):
        return self._request(
            "POST",
            endpoint,
            headers=headers,
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            timeout_seconds=timeout_seconds,
        )

    def get_json(self, endpoint, *, headers, timeout_seconds):
        return self._request("GET", endpoint, headers=headers, body=None, timeout_seconds=timeout_seconds)

    def get_bytes(self, endpoint, *, headers, timeout_seconds):
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or not (
            parsed.hostname == "api.seedance.nz" or parsed.hostname.endswith(".seedance.nz")
        ):
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Provider download endpoint is not authorized",
                category="authorization",
            )
        response = self._request(
            "GET",
            endpoint,
            headers=headers,
            body=None,
            timeout_seconds=timeout_seconds,
            allow_download=True,
        )
        if response.status < 200 or response.status >= 300:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Provider image download failed",
                category="provider",
                details={"http_status": response.status},
            )
        return response.body


def _json_object(response: SeedanceNzHttpResponse) -> dict[str, object]:
    try:
        value = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Provider response was not valid JSON",
            category="provider",
            details={"cause_type": type(exc).__name__},
        ) from exc
    if not isinstance(value, dict):
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Provider response was not a JSON object",
            category="provider",
        )
    return value


def _image_shape(content: bytes) -> tuple[str, int, int]:
    if len(content) >= 24 and content.startswith(b"\x89PNG\r\n\x1a\n") and content[12:16] == b"IHDR":
        width, height = struct.unpack(">II", content[16:24])
        return "image/png", width, height
    if len(content) >= 4 and content[:2] == b"\xff\xd8":
        index = 2
        while index + 9 <= len(content):
            if content[index] != 0xFF:
                index += 1
                continue
            marker = content[index + 1]
            index += 2
            if marker in (0xD8, 0xD9):
                continue
            if index + 2 > len(content):
                break
            segment_length = int.from_bytes(content[index : index + 2], "big")
            if segment_length < 2 or index + segment_length > len(content):
                break
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                height = int.from_bytes(content[index + 3 : index + 5], "big")
                width = int.from_bytes(content[index + 5 : index + 7], "big")
                return "image/jpeg", width, height
            index += segment_length
    raise ImagePanelError(
        ImagePanelErrorCode.PROVIDER_FAILED,
        "Provider image dimensions could not be verified",
        category="provider",
    )


class SeedanceNzImageAdapter(ImageProviderAdapter):
    def __init__(
        self,
        api_key: str,
        *,
        transport: SeedanceNzTransport | None = None,
        sleep: Callable[[float], None] | None = None,
        max_poll_attempts: int = MAX_POLL_ATTEMPTS,
        reference_image_urls: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("SEEDANCE_NZ_API_KEY is required")
        if max_poll_attempts < 1:
            raise ValueError("max_poll_attempts must be positive")
        self._api_key = key
        self._transport = transport or SeedanceNzHttpClient()
        self._sleep = sleep or time.sleep
        self._max_poll_attempts = max_poll_attempts
        self._reference_image_urls = {
            str(item_id): tuple(urls)
            for item_id, urls in (reference_image_urls or {}).items()
        }
        if any(len(urls) > 10 for urls in self._reference_image_urls.values()):
            raise ValueError("reference_image_urls supports at most 10 URLs per item")
        self._last_receipt: SeedanceNzProviderReceipt | None = None

    @classmethod
    def from_environment(cls, **kwargs):
        return cls(api_key=os.environ.get("SEEDANCE_NZ_API_KEY", ""), **kwargs)

    @property
    def provider_id(self) -> str:
        return "seedance-nz-image"

    @property
    def last_receipt(self) -> SeedanceNzProviderReceipt:
        if self._last_receipt is None:
            raise RuntimeError("No Seedance.nz Provider receipt is available")
        return self._last_receipt

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _generate(self, invocation: ProviderInvocation, *, cancellation: CancellationToken) -> ProviderAsset:
        if cancellation.cancelled:
            raise ImagePanelError(ImagePanelErrorCode.CANCELLED, "Generation was cancelled", category="state")
        if invocation.profile.provider_id != self.provider_id or invocation.profile.model_id not in SEEDANCE_NZ_ALLOWED_MODELS:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Provider model binding is not authorized for Seedance.nz",
                category="authorization",
            )
        payload: dict[str, object] = {
            "model": invocation.profile.model_id,
            "prompt": invocation.compiled_prompt,
            "metadata": {"resolution": "1k", "output_format": "jpeg"},
        }
        reference_urls = self._reference_image_urls.get(invocation.item.item_id, ())
        if reference_urls:
            if invocation.profile.model_id != SEEDANCE_NZ_DEFAULT_I2I_MODEL:
                raise ImagePanelError(
                    ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                    "Reference images require the Seedance.nz image-to-image model",
                    category="authorization",
                )
            payload["images"] = list(reference_urls)
        submit = self._transport.post_json(
            SEEDANCE_NZ_IMAGE_SUBMIT_ENDPOINT,
            headers=self._headers(),
            payload=payload,
            timeout_seconds=min(invocation.timeout_seconds, MAX_TIMEOUT_SECONDS),
        )
        error_body = submit.body.decode("utf-8", errors="replace").replace(self._api_key, "[REDACTED]")
        self._last_receipt = SeedanceNzProviderReceipt(
            endpoint=SEEDANCE_NZ_IMAGE_SUBMIT_ENDPOINT,
            model_id=invocation.profile.model_id,
            task_id=None,
            http_status=submit.status,
            elapsed_ms=submit.elapsed_ms,
            error_body=error_body if submit.status < 200 or submit.status >= 300 else None,
        )
        if submit.status == 401 or submit.status == 403:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Seedance.nz Provider authorization failed",
                category="authorization",
            )
        if submit.status < 200 or submit.status >= 300:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Provider returned a non-success HTTP status",
                category="provider",
                details={"http_status": submit.status},
            )
        document = _json_object(submit)
        task_id = document.get("task_id") or document.get("id")
        if not isinstance(task_id, str):
            nested_data = document.get("data")
            if isinstance(nested_data, Mapping):
                task_id = nested_data.get("task_id") or nested_data.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ImagePanelError(ImagePanelErrorCode.PROVIDER_FAILED, "Provider response did not contain a task_id", category="provider")

        result_url: str | None = None
        last_poll: SeedanceNzHttpResponse | None = None
        for _ in range(self._max_poll_attempts):
            if cancellation.cancelled:
                raise ImagePanelError(ImagePanelErrorCode.CANCELLED, "Generation was cancelled", category="state")
            last_poll = self._transport.get_json(
                SEEDANCE_NZ_IMAGE_TASK_ENDPOINT.format(task_id=task_id),
                headers=self._headers(),
                timeout_seconds=min(invocation.timeout_seconds, MAX_TIMEOUT_SECONDS),
            )
            if last_poll.status == 401 or last_poll.status == 403:
                raise ImagePanelError(
                    ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                    "Seedance.nz Provider authorization failed while polling",
                    category="authorization",
                )
            if last_poll.status < 200 or last_poll.status >= 300:
                raise ImagePanelError(
                    ImagePanelErrorCode.PROVIDER_FAILED,
                    "Provider polling returned a non-success HTTP status",
                    category="provider",
                    details={"http_status": last_poll.status},
                )
            poll_document = _json_object(last_poll)
            status = str(poll_document.get("status", "")).upper()
            if status == "SUCCESS":
                data = poll_document.get("data")
                if isinstance(data, Mapping):
                    result_url = data.get("result_url") if isinstance(data.get("result_url"), str) else None
                break
            if status == "FAILURE":
                raise ImagePanelError(
                    ImagePanelErrorCode.PROVIDER_FAILED,
                    "Seedance.nz image generation failed",
                    category="provider",
                    details={"task_id": task_id},
                )
            if status not in {"NOT_START", "IN_PROGRESS"}:
                raise ImagePanelError(ImagePanelErrorCode.PROVIDER_FAILED, "Provider returned an unknown task status", category="provider")
            self._sleep(0.05)
        else:
            raise ImagePanelError(ImagePanelErrorCode.PROVIDER_TIMEOUT, "Seedance.nz image task polling timed out", category="provider")

        if not result_url:
            raise ImagePanelError(ImagePanelErrorCode.PROVIDER_FAILED, "Provider success response did not contain result_url", category="provider")
        content = self._transport.get_bytes(
            result_url,
            headers=self._headers(),
            timeout_seconds=min(invocation.timeout_seconds, MAX_TIMEOUT_SECONDS),
        )
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise ImagePanelError(ImagePanelErrorCode.PROVIDER_FAILED, "Provider image bytes were empty or too large", category="provider")
        content_type, width, height = _image_shape(content)
        if width != invocation.item.width or height != invocation.item.height:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Provider image dimensions did not match requested dimensions",
                category="provider",
                details={
                    "requested_width": invocation.item.width,
                    "requested_height": invocation.item.height,
                    "actual_width": width,
                    "actual_height": height,
                },
            )
        digest = hashlib.sha256(content).hexdigest()
        self._last_receipt = SeedanceNzProviderReceipt(
            endpoint=SEEDANCE_NZ_IMAGE_TASK_ENDPOINT.format(task_id=task_id),
            model_id=invocation.profile.model_id,
            task_id=task_id,
            http_status=last_poll.status if last_poll else submit.status,
            elapsed_ms=(last_poll.elapsed_ms if last_poll else 0),
            provider_asset_id=task_id,
            result_url=result_url,
            content_type=content_type,
            byte_size=len(content),
            sha256=digest,
            width=width,
            height=height,
        )
        return ProviderAsset(
            provider_asset_id=task_id,
            content=content,
            content_type=content_type,
            width=width,
            height=height,
            provider_metadata=MappingProxyType(self.last_receipt.to_dict()),
        )


class FakeSeedanceNzImageAdapter(ImageProviderAdapter):
    """Deterministic in-memory adapter for offline tests and fixtures."""

    def __init__(self, *, terminal_status: str = "SUCCESS", content: bytes | None = None) -> None:
        self.terminal_status = terminal_status.upper()
        self.content = bytes(content or deterministic_png(1024, 1024, seed="seedance-nz-fake-task-001"))
        self.network_calls = 0

    @property
    def provider_id(self) -> str:
        return "seedance-nz-image"

    def _generate(self, invocation: ProviderInvocation, *, cancellation: CancellationToken) -> ProviderAsset:
        if cancellation.cancelled:
            raise ImagePanelError(ImagePanelErrorCode.CANCELLED, "Generation was cancelled", category="state")
        if self.terminal_status != "SUCCESS":
            raise ImagePanelError(ImagePanelErrorCode.PROVIDER_FAILED, "Synthetic Seedance.nz task failed", category="provider")
        content_type, width, height = _image_shape(self.content)
        return ProviderAsset(
            provider_asset_id="seedance-nz-fake-task-001",
            content=self.content,
            content_type=content_type,
            width=width,
            height=height,
            provider_metadata=MappingProxyType({"provider_network_performed": False, "network_calls": self.network_calls}),
        )
