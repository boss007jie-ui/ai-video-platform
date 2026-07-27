"""Strict PackyAPI GPT Image 2 adapter for independent panel assets."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import time
from types import MappingProxyType
from typing import Callable, Mapping, Protocol
from urllib.parse import unquote, urlsplit

from .adapters import (
    ImageProviderAdapter,
    ProviderAsset,
    ProviderInputAsset,
    ProviderInvocation,
)
from .errors import ImagePanelError, ImagePanelErrorCode
from .models import CancellationToken


GENERATIONS_ENDPOINT = "https://www.packyapi.ai/v1/images/generations"
EDITS_ENDPOINT = "https://www.packyapi.ai/v1/images/edits"
PACKY_MODEL = "gpt-image-2"
MIN_PIXELS = 655_360
MAX_PIXELS = 8_294_400
MAX_DIMENSION = 3_840
DIMENSION_MULTIPLE = 16
MAX_ASPECT_RATIO = 3
MAX_TIMEOUT_SECONDS = 300.0
MAX_RESPONSE_BYTES = 67_108_864
MAX_IMAGE_BYTES = 33_554_432


@dataclass(frozen=True, slots=True)
class PackyHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    elapsed_ms: int


class PackyTransport(Protocol):
    def post_json(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> PackyHttpResponse: ...

    def post_multipart(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        content_type: str,
        timeout_seconds: float,
    ) -> PackyHttpResponse: ...


@dataclass(frozen=True, slots=True)
class PackyProviderReceipt:
    endpoint: str
    model_id: str
    http_status: int
    elapsed_ms: int
    provider_network_performed: bool = True
    provider_asset_id: str | None = None
    content_type: str | None = None
    byte_size: int | None = None
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "model_id": self.model_id,
            "http_status": self.http_status,
            "elapsed_ms": self.elapsed_ms,
            "provider_network_performed": self.provider_network_performed,
            "provider_asset_id": self.provider_asset_id,
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "width": self.width,
            "height": self.height,
        }


class PackyHttpClient:
    """One-shot HTTPS client with method-specific exact endpoint allowlists."""

    def __init__(
        self,
        *,
        connection_factory: Callable[..., http.client.HTTPSConnection] = http.client.HTTPSConnection,
    ) -> None:
        self._connection_factory = connection_factory

    def post_json(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> PackyHttpResponse:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return self._post(
            endpoint,
            expected_endpoint=GENERATIONS_ENDPOINT,
            headers=headers,
            body=body,
            timeout_seconds=timeout_seconds,
        )

    def post_multipart(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        content_type: str,
        timeout_seconds: float,
    ) -> PackyHttpResponse:
        if not content_type.startswith("multipart/form-data; boundary="):
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Packy multipart content type is not authorized",
                category="authorization",
            )
        return self._post(
            endpoint,
            expected_endpoint=EDITS_ENDPOINT,
            headers={**headers, "Content-Type": content_type},
            body=body,
            timeout_seconds=timeout_seconds,
        )

    def _post(
        self,
        endpoint: str,
        *,
        expected_endpoint: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> PackyHttpResponse:
        if endpoint != expected_endpoint:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Packy endpoint is not authorized",
                category="authorization",
                details={"endpoint": endpoint},
            )
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.packyapi.ai"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Packy endpoint is not authorized",
                category="authorization",
            )
        timeout = min(float(timeout_seconds), MAX_TIMEOUT_SECONDS)
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        connection = self._connection_factory(parsed.hostname, port=parsed.port, timeout=timeout)
        started = time.monotonic()
        try:
            connection.request("POST", parsed.path, body=body, headers=dict(headers))
            response = connection.getresponse()
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_RESPONSE_BYTES:
                raise _provider_error("Provider response exceeded the authorized size limit")
            return PackyHttpResponse(
                status=int(response.status),
                headers={str(key).lower(): str(value) for key, value in response.getheaders()},
                body=response_body,
                elapsed_ms=max(0, round((time.monotonic() - started) * 1000)),
            )
        except TimeoutError as exc:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_TIMEOUT,
                "Packy request exceeded the configured timeout",
                category="provider",
            ) from exc
        except ImagePanelError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise _provider_error(
                "Packy network request failed",
                cause_type=type(exc).__name__,
                endpoint=endpoint,
            ) from exc
        finally:
            connection.close()


def _provider_error(message: str, **details: object) -> ImagePanelError:
    return ImagePanelError(
        ImagePanelErrorCode.PROVIDER_FAILED,
        message,
        category="provider",
        retryable=False,
        details=details,
    )


def _validate_size(width: int, height: int) -> None:
    pixels = width * height
    smaller = min(width, height)
    larger = max(width, height)
    if (
        width <= 0
        or height <= 0
        or width % DIMENSION_MULTIPLE
        or height % DIMENSION_MULTIPLE
        or larger > MAX_DIMENSION
        or smaller == 0
        or larger > smaller * MAX_ASPECT_RATIO
        or pixels < MIN_PIXELS
        or pixels > MAX_PIXELS
    ):
        raise _provider_error(
            "Requested Packy image size is outside the authorized contract",
            width=width,
            height=height,
            min_pixels=MIN_PIXELS,
            max_pixels=MAX_PIXELS,
        )


def _local_file_path(asset: ProviderInputAsset) -> Path:
    parsed = urlsplit(asset.uri)
    if (
        not asset.uri.startswith("file://")
        or parsed.scheme != "file"
        or parsed.query
        or parsed.fragment
        or re.search(r"%(?![0-9A-Fa-f]{2})", parsed.path) is not None
        or (parsed.netloc and parsed.netloc.lower() != "localhost")
    ):
        raise _provider_error(
            "Packy edit input must be an approved local file asset",
            asset_id=asset.asset_id,
            reason="invalid_file_uri",
        )
    path_text = unquote(parsed.path)
    if os.name == "nt" and len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
        path_text = path_text[1:]
    path = Path(path_text)
    if not path.is_absolute():
        raise _provider_error(
            "Packy edit input must be an absolute local file asset",
            asset_id=asset.asset_id,
            reason="invalid_file_uri",
        )
    return path


def _read_input_image(asset: ProviderInputAsset) -> tuple[Path, str, bytes]:
    if asset.media_type.lower() not in {"image/png", "image/jpeg"}:
        raise _provider_error(
            "Packy edit input must declare PNG or JPEG media",
            asset_id=asset.asset_id,
            reason="unsupported_media_type",
        )
    if not isinstance(asset.metadata.get("approval_ref"), str) or not asset.metadata["approval_ref"]:
        raise _provider_error(
            "Packy edit input was not approved",
            asset_id=asset.asset_id,
            reason="approval_missing",
        )
    path = _local_file_path(asset)
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise _provider_error(
            "Packy edit input file was not found",
            asset_id=asset.asset_id,
            reason="file_missing",
        ) from exc
    except (PermissionError, OSError) as exc:
        raise _provider_error(
            "Packy edit input file could not be read",
            asset_id=asset.asset_id,
            reason="file_unreadable",
        ) from exc
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        actual_type = "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        actual_type = "image/jpeg"
    else:
        raise _provider_error(
            "Packy edit input was not a PNG or JPEG image",
            asset_id=asset.asset_id,
            reason="unsupported_image_format",
        )
    if actual_type != asset.media_type.lower():
        raise _provider_error(
            "Packy edit input media type did not match file bytes",
            asset_id=asset.asset_id,
            reason="media_type_mismatch",
        )
    return path, actual_type, content


def _multipart_body(
    invocation: ProviderInvocation,
    *,
    filename: str,
    image_type: str,
    image_bytes: bytes,
) -> tuple[str, bytes]:
    boundary = "packy-" + hashlib.sha256(
        f"{invocation.request_hash}:{invocation.item.item_id}".encode("utf-8")
    ).hexdigest()[:24]
    fields = (
        ("model", PACKY_MODEL),
        ("prompt", invocation.compiled_prompt),
        ("quality", "high"),
        ("size", f"{invocation.item.width}x{invocation.item.height}"),
        ("n", "1"),
        ("output_format", "png"),
        ("response_format", "b64_json"),
        ("input_fidelity", "high"),
    )
    chunks: list[bytes] = []
    for name, value in fields:
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    safe_filename = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    chunks.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{safe_filename}"\r\n'
            f"Content-Type: {image_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(image_bytes)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def _decode_image(value: object) -> tuple[bytes, str, int, int]:
    if not isinstance(value, str) or not value:
        raise _provider_error("Provider response did not contain inline image bytes")
    try:
        content = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise _provider_error("Provider image bytes were not valid base64") from exc
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise _provider_error("Provider image bytes exceeded the authorized size limit")
    if (
        len(content) >= 24
        and content.startswith(b"\x89PNG\r\n\x1a\n")
        and content[12:16] == b"IHDR"
    ):
        width = int.from_bytes(content[16:20], "big")
        height = int.from_bytes(content[20:24], "big")
        return content, "image/png", width, height
    if len(content) >= 4 and content.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 <= len(content):
            if content[index] != 0xFF:
                index += 1
                continue
            marker = content[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(content):
                break
            segment_length = int.from_bytes(content[index : index + 2], "big")
            if segment_length < 2 or index + segment_length > len(content):
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                height = int.from_bytes(content[index + 3 : index + 5], "big")
                width = int.from_bytes(content[index + 5 : index + 7], "big")
                return content, "image/jpeg", width, height
            index += segment_length
    raise _provider_error("Provider result was not a verifiable PNG or JPEG image")


class PackyImage2Adapter(ImageProviderAdapter):
    def __init__(
        self,
        api_key: str,
        *,
        transport: PackyTransport | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("PACKY_API_KEY is required")
        self._api_key = key
        self._transport = transport or PackyHttpClient()
        self._last_receipt: PackyProviderReceipt | None = None
        self._last_asset: ProviderAsset | None = None

    @classmethod
    def from_environment(cls) -> "PackyImage2Adapter":
        return cls(api_key=os.environ.get("PACKY_API_KEY", ""))

    @property
    def provider_id(self) -> str:
        return "packy-image2"

    @property
    def last_receipt(self) -> PackyProviderReceipt:
        if self._last_receipt is None:
            raise RuntimeError("No Packy Provider receipt is available")
        return self._last_receipt

    @property
    def last_asset(self) -> ProviderAsset:
        if self._last_asset is None:
            raise RuntimeError("No Packy Provider asset is available")
        return self._last_asset

    def _generate(
        self,
        invocation: ProviderInvocation,
        *,
        cancellation: CancellationToken,
    ) -> ProviderAsset:
        if cancellation.cancelled:
            raise ImagePanelError(
                ImagePanelErrorCode.CANCELLED,
                "Generation was cancelled",
                category="state",
            )
        if (
            invocation.profile.provider_id != self.provider_id
            or invocation.profile.model_id != PACKY_MODEL
        ):
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Packy model binding is not authorized",
                category="authorization",
            )
        _validate_size(invocation.item.width, invocation.item.height)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        endpoint = GENERATIONS_ENDPOINT
        if invocation.input_assets:
            if len(invocation.input_assets) != 1:
                raise _provider_error(
                    "Packy edits require exactly one approved local image",
                    image_count=len(invocation.input_assets),
                )
            path, image_type, image_bytes = _read_input_image(invocation.input_assets[0])
            content_type, body = _multipart_body(
                invocation,
                filename=path.name,
                image_type=image_type,
                image_bytes=image_bytes,
            )
            endpoint = EDITS_ENDPOINT
            response = self._transport.post_multipart(
                endpoint,
                headers=headers,
                body=body,
                content_type=content_type,
                timeout_seconds=invocation.timeout_seconds,
            )
        else:
            response = self._transport.post_json(
                endpoint,
                headers={**headers, "Content-Type": "application/json"},
                payload={
                    "model": PACKY_MODEL,
                    "prompt": invocation.compiled_prompt,
                    "quality": "high",
                    "size": f"{invocation.item.width}x{invocation.item.height}",
                    "n": 1,
                    "output_format": "png",
                    "response_format": "b64_json",
                },
                timeout_seconds=invocation.timeout_seconds,
            )
        self._last_receipt = PackyProviderReceipt(
            endpoint=endpoint,
            model_id=PACKY_MODEL,
            http_status=response.status,
            elapsed_ms=response.elapsed_ms,
        )
        if response.status < 200 or response.status >= 300:
            raise _provider_error(
                "Provider returned a non-success HTTP status",
                endpoint=endpoint,
                http_status=response.status,
            )
        try:
            document = json.loads(response.body)
            item = document["data"][0]
            value = item["b64_json"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise _provider_error("Provider response did not contain an inline image result") from exc
        content, content_type, width, height = _decode_image(value)
        if width != invocation.item.width or height != invocation.item.height:
            raise _provider_error(
                "Provider image dimensions did not match requested dimensions",
                requested_width=invocation.item.width,
                requested_height=invocation.item.height,
                actual_width=width,
                actual_height=height,
            )
        provider_asset_id = str(
            item.get("id")
            or response.headers.get("x-request-id")
            or f"packy:{invocation.request_id}:{invocation.item.item_id}"
        )
        receipt = PackyProviderReceipt(
            endpoint=endpoint,
            model_id=PACKY_MODEL,
            http_status=response.status,
            elapsed_ms=response.elapsed_ms,
            provider_asset_id=provider_asset_id,
            content_type=content_type,
            byte_size=len(content),
            width=width,
            height=height,
        )
        asset = ProviderAsset(
            provider_asset_id=provider_asset_id,
            content=content,
            content_type=content_type,
            width=width,
            height=height,
            provider_metadata=MappingProxyType(receipt.to_dict()),
        )
        self._last_receipt = receipt
        self._last_asset = asset
        return asset
