"""Strict Yunwu image Provider adapters authorized by FTG-P-003."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import struct
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


YUNWU_AUTHORIZATION_ID = "FTG-P-003"
NANO_BANANA_MODEL = "gemini-3.1-flash-image-preview"
IMAGE2_MODELS = frozenset({"gpt-image-2", "gpt-image-2-all"})
NANO_BANANA_ENDPOINT = (
    "https://yunwu.ai/v1beta/models/"
    "gemini-3.1-flash-image-preview:generateContent"
)
IMAGE2_ENDPOINT = "https://yunwu.ai/v1/images/generations"
IMAGE2_UPLOAD_ENDPOINT = "https://imageproxy.zhongzhuan.chat/api/upload"
ALLOWED_ENDPOINTS = frozenset(
    {
        NANO_BANANA_ENDPOINT,
        IMAGE2_ENDPOINT,
        IMAGE2_UPLOAD_ENDPOINT,
    }
)
MAX_TIMEOUT_SECONDS = 300.0
MAX_RESPONSE_BYTES = 67_108_864
MAX_IMAGE_BYTES = 33_554_432
MAX_NANO_INPUT_IMAGES = 9
MAX_NANO_INPUT_IMAGE_BYTES = 10 * 1024 * 1024
MAX_NANO_REQUEST_BYTES = 18 * 1024 * 1024


def _serialize_json_payload(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
def _input_asset_error(asset_id: str, reason: str, message: str) -> ImagePanelError:

    return ImagePanelError(
        ImagePanelErrorCode.PROVIDER_FAILED,
        message,
        category="provider",
        retryable=False,
        details={"asset_id": asset_id, "reason": reason},
    )


def _local_file_path(asset: ProviderInputAsset) -> Path:
    parsed = urlsplit(asset.uri)
    if (
        not asset.uri.startswith("file://")
        or parsed.scheme != "file"
        or parsed.query
        or re.search(r"%(?![0-9A-Fa-f]{2})", parsed.path) is not None
        or parsed.fragment
    ):
        raise _input_asset_error(
            asset.asset_id,
            "invalid_file_uri",
            "Input image URI must be a valid local file URI",
        )
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        raise _input_asset_error(
            asset.asset_id,
            "non_local_file_uri",
            "Input image URI must identify a local file",
        )
    path_text = unquote(parsed.path)
    if (
        os.name == "nt"
        and len(path_text) >= 3
        and path_text[0] == "/"
        and path_text[2] == ":"
    ):
        path_text = path_text[1:]
    path = Path(path_text)
    if not path.is_absolute():
        raise _input_asset_error(
            asset.asset_id,
            "invalid_file_uri",
            "Input image URI must identify an absolute local file",
        )
    return path


def _input_image_mime(asset_id: str, content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    raise _input_asset_error(
        asset_id,
        "unsupported_image_format",
        "Input image format is not supported",
    )


def _read_input_image(asset: ProviderInputAsset) -> tuple[str, bytes]:
    path = _local_file_path(asset)
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise _input_asset_error(
            asset.asset_id,
            "file_missing",
            "Input image file was not found",
        ) from exc
    except (PermissionError, OSError) as exc:
        raise _input_asset_error(
            asset.asset_id,
            "file_unreadable",
            "Input image file could not be read",
        ) from exc
    if len(content) > MAX_NANO_INPUT_IMAGE_BYTES:
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Input image bytes exceeded the authorized size limit",
            category="provider",
            retryable=False,
            details={
                "asset_id": asset.asset_id,
                "reason": "image_too_large",
                "actual_byte_size": len(content),
                "max_byte_size": MAX_NANO_INPUT_IMAGE_BYTES,
            },
        )
    return _input_image_mime(asset.asset_id, content), content


def _nano_payload(
    invocation: ProviderInvocation,
) -> tuple[dict[str, object], dict[str, object]]:
    parts: list[dict[str, object]] = [{"text": invocation.compiled_prompt}]
    image_assets: list[ProviderInputAsset] = []
    skipped_input_asset_ids: list[str] = []
    for asset in invocation.input_assets:
        media_type = asset.media_type.strip().lower()
        if media_type == "image" or media_type.startswith("image/"):
            image_assets.append(asset)
        else:
            skipped_input_asset_ids.append(asset.asset_id)
    if len(image_assets) > MAX_NANO_INPUT_IMAGES:
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Input image count exceeded the authorized limit",
            category="provider",
            retryable=False,
            details={
                "image_count": len(image_assets),
                "max_image_count": MAX_NANO_INPUT_IMAGES,
            },
        )
    for asset in image_assets:
        mime_type, content = _read_input_image(asset)
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(content).decode("ascii"),
                }
            }
        )
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    actual_byte_size = len(_serialize_json_payload(payload))
    if actual_byte_size > MAX_NANO_REQUEST_BYTES:
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Nano Banana request body exceeded the authorized size limit",
            category="provider",
            retryable=False,
            details={
                "reason": "request_body_too_large",
                "actual_byte_size": actual_byte_size,
                "max_byte_size": MAX_NANO_REQUEST_BYTES,
            },
        )
    return payload, {"skipped_input_asset_ids": skipped_input_asset_ids}


@dataclass(frozen=True, slots=True)
class YunwuHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class YunwuProviderReceipt:
    endpoint: str
    model_id: str
    http_status: int
    elapsed_ms: int
    provider_network_performed: bool = True
    cost_fields: Mapping[str, object] = MappingProxyType({})
    details: Mapping[str, object] = MappingProxyType({})
    provider_asset_id: str | None = None
    content_type: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    upload_http_status: int | None = None
    error_body: str | None = None

    def to_dict(self) -> dict[str, object]:
        document = {
            "endpoint": self.endpoint,
            "model_id": self.model_id,
            "http_status": self.http_status,
            "elapsed_ms": self.elapsed_ms,
            "provider_network_performed": self.provider_network_performed,
            "cost_fields": dict(self.cost_fields),
            "provider_asset_id": self.provider_asset_id,
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "upload_http_status": self.upload_http_status,
            "error_body": self.error_body,
        }
        if self.details:
            document["details"] = dict(self.details)
        return document


class YunwuJsonTransport(Protocol):
    def post_json(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> YunwuHttpResponse: ...


class YunwuHttpClient:
    """One-shot HTTPS JSON client with an exact endpoint allowlist and no redirects."""

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
    ) -> YunwuHttpResponse:
        if endpoint not in ALLOWED_ENDPOINTS:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Provider endpoint is not authorized",
                category="authorization",
                details={"endpoint": endpoint},
            )
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Provider endpoint is not authorized",
                category="authorization",
            )
        timeout = min(float(timeout_seconds), MAX_TIMEOUT_SECONDS)
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        body = _serialize_json_payload(payload)
        connection = self._connection_factory(parsed.hostname, port=parsed.port, timeout=timeout)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        started = time.monotonic()
        try:
            connection.request("POST", path, body=body, headers=dict(headers))
            response = connection.getresponse()
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
            elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
            if len(response_body) > MAX_RESPONSE_BYTES:
                raise ImagePanelError(
                    ImagePanelErrorCode.PROVIDER_FAILED,
                    "Provider response exceeded the authorized size limit",
                    category="provider",
                )
            response_headers = {
                str(key).lower(): str(value)
                for key, value in response.getheaders()
            }
            return YunwuHttpResponse(
                int(response.status),
                response_headers,
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
                details={"cause_type": type(exc).__name__, "endpoint": endpoint},
            ) from exc
        finally:
            connection.close()


def _json_object(response: YunwuHttpResponse) -> dict[str, object]:
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


def _cost_fields(document: Mapping[str, object]) -> Mapping[str, object]:
    fields = {
        key: document[key]
        for key in ("usageMetadata", "usage", "cost", "credits")
        if key in document
    }
    return MappingProxyType(fields)


def _decode_base64(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Provider response did not contain inline image bytes",
            category="provider",
        )
    try:
        content = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Provider image bytes were not valid base64",
            category="provider",
        ) from exc
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Provider image bytes were empty or exceeded the authorized size limit",
            category="provider",
        )
    return content


def _image_shape(
    content: bytes,
    supplied_content_type: str | None = None,
) -> tuple[str, int, int]:
    if (
        len(content) >= 24
        and content.startswith(b"\x89PNG\r\n\x1a\n")
        and content[12:16] == b"IHDR"
    ):
        width, height = struct.unpack(">II", content[16:24])
        return supplied_content_type or "image/png", width, height
    if len(content) >= 4 and content[:2] == b"\xff\xd8":
        index = 2
        while index + 9 <= len(content):
            if content[index] != 0xFF:
                index += 1
                continue
            marker = content[index + 1]
            index += 2
            if marker in frozenset({0xD8, 0xD9}):
                continue
            if index + 2 > len(content):
                break
            segment_length = int.from_bytes(content[index : index + 2], "big")
            if segment_length < 2 or index + segment_length > len(content):
                break
            if marker in frozenset(
                {
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
                }
            ):
                height = int.from_bytes(content[index + 3 : index + 5], "big")
                width = int.from_bytes(content[index + 5 : index + 7], "big")
                return supplied_content_type or "image/jpeg", width, height
            index += segment_length
    raise ImagePanelError(
        ImagePanelErrorCode.PROVIDER_FAILED,
        "Provider image dimensions could not be verified",
        category="provider",
    )


class _YunwuAdapter(ImageProviderAdapter):
    endpoint: str
    allowed_models: frozenset[str]

    def __init__(
        self,
        api_key: str,
        *,
        transport: YunwuJsonTransport | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("YUNWU_API_KEY is required")
        self._api_key = key
        self._transport = transport or YunwuHttpClient()
        self._last_receipt: YunwuProviderReceipt | None = None
        self._last_asset: ProviderAsset | None = None

    @classmethod
    def from_environment(cls):
        return cls(api_key=os.environ.get("YUNWU_API_KEY", ""))

    @property
    def last_receipt(self) -> YunwuProviderReceipt:
        if self._last_receipt is None:
            raise RuntimeError("No Yunwu Provider receipt is available")
        return self._last_receipt

    @property
    def last_asset(self) -> ProviderAsset:
        if self._last_asset is None:
            raise RuntimeError("No Yunwu Provider asset is available")
        return self._last_asset

    def _authorize_invocation(self, invocation: ProviderInvocation) -> None:
        if (
            YUNWU_AUTHORIZATION_ID != "FTG-P-003"
            or invocation.profile.provider_id != self.provider_id
            or invocation.profile.model_id not in self.allowed_models
        ):
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Provider model binding is not authorized by FTG-P-003",
                category="authorization",
            )

    def _post(
        self,
        invocation: ProviderInvocation,
        payload: Mapping[str, object],
        details: Mapping[str, object] | None = None,
    ) -> tuple[YunwuHttpResponse, dict[str, object]]:
        response = self._transport.post_json(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            payload=payload,
            timeout_seconds=min(invocation.timeout_seconds, MAX_TIMEOUT_SECONDS),
        )
        error_body = None
        if response.status < 200 or response.status >= 300:
            error_body = response.body.decode("utf-8", errors="replace").replace(
                self._api_key,
                "[REDACTED]",
            )
        self._last_receipt = YunwuProviderReceipt(
            endpoint=self.endpoint,
            model_id=invocation.profile.model_id,
            http_status=response.status,
            elapsed_ms=response.elapsed_ms,
            error_body=error_body,
            details=MappingProxyType(dict(details or {})),
        )
        if response.status < 200 or response.status >= 300:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Provider returned a non-success HTTP status",
                category="provider",
                retryable=False,
                details={"endpoint": self.endpoint, "http_status": response.status},
            )
        document = _json_object(response)
        return response, document

    def _finish(
        self,
        *,
        invocation: ProviderInvocation,
        response: YunwuHttpResponse,
        document: Mapping[str, object],
        provider_asset_id: str,
        content: bytes,
        content_type: str | None,
        details: Mapping[str, object] | None = None,
    ) -> ProviderAsset:
        verified_content_type, width, height = _image_shape(content, content_type)
        digest = hashlib.sha256(content).hexdigest()
        receipt = YunwuProviderReceipt(
            endpoint=self.endpoint,
            model_id=invocation.profile.model_id,
            http_status=response.status,
            elapsed_ms=response.elapsed_ms,
            cost_fields=_cost_fields(document),
            details=MappingProxyType(dict(details or {})),
            provider_asset_id=provider_asset_id,
            content_type=verified_content_type,
            byte_size=len(content),
            sha256=digest,
            width=width,
            height=height,
        )
        self._last_receipt = receipt
        if (
            width != invocation.item.width
            or height != invocation.item.height
        ):
            self._last_asset = None
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Provider image dimensions did not match requested dimensions",
                category="provider",
                retryable=False,
                details={
                    "requested_width": invocation.item.width,
                    "requested_height": invocation.item.height,
                    "actual_width": width,
                    "actual_height": height,
                },
            )
        asset = ProviderAsset(
            provider_asset_id=provider_asset_id,
            content=content,
            content_type=verified_content_type,
            width=width,
            height=height,
            provider_metadata=MappingProxyType(receipt.to_dict()),
        )
        self._last_asset = asset
        return asset


class YunwuNanoBananaAdapter(_YunwuAdapter):
    endpoint = NANO_BANANA_ENDPOINT
    allowed_models = frozenset({NANO_BANANA_MODEL})

    @property
    def provider_id(self) -> str:
        return "yunwu-nano-banana"

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
        self._authorize_invocation(invocation)
        payload, receipt_details = _nano_payload(invocation)
        response, document = self._post(
            invocation,
            payload,
            details=receipt_details,
        )
        try:
            candidates = document["candidates"]
            candidate = candidates[0]
            parts = candidate["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Provider response did not contain an image candidate",
                category="provider",
                details={"cause_type": type(exc).__name__},
            ) from exc
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, Mapping):
                continue
            content = _decode_base64(inline.get("data"))
            provider_asset_id = str(
                document.get("responseId")
                or response.headers.get("x-request-id")
                or f"yunwu:{invocation.request_id}:{invocation.item.item_id}"
            )
            return self._finish(
                invocation=invocation,
                response=response,
                document=document,
                provider_asset_id=provider_asset_id,
                content=content,
                content_type=str(inline.get("mimeType")) if inline.get("mimeType") else None,
                details=receipt_details,
            )
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Provider response did not contain inline image bytes",
            category="provider",
        )


class YunwuImage2Adapter(_YunwuAdapter):
    endpoint = IMAGE2_ENDPOINT
    allowed_models = IMAGE2_MODELS

    @property
    def provider_id(self) -> str:
        return "yunwu-image2"

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
        self._authorize_invocation(invocation)
        response, document = self._post(
            invocation,
            {
                "model": invocation.profile.model_id,
                "prompt": invocation.compiled_prompt,
                "quality": "low",
                "size": f"{invocation.item.width}x{invocation.item.height}",
                "n": 1,
                "output_format": "png",
            },
        )
        try:
            item = document["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Provider response did not contain an image result",
                category="provider",
                details={"cause_type": type(exc).__name__},
            ) from exc
        if not isinstance(item, Mapping) or "b64_json" not in item:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Provider returned a non-inline image result; downloads are not authorized",
                category="provider",
            )
        content = _decode_base64(item.get("b64_json"))
        provider_asset_id = str(
            item.get("id")
            or response.headers.get("x-request-id")
            or f"yunwu:{invocation.request_id}:{invocation.item.item_id}"
        )
        return self._finish(
            invocation=invocation,
            response=response,
            document=document,
            provider_asset_id=provider_asset_id,
            content=content,
            content_type=None,
        )
