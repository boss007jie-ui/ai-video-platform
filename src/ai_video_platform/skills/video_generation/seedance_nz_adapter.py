"""Seedance.nz production seam and deterministic offline test doubles."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
import re
from time import monotonic
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .adapters import AdapterFailure
from .errors import contains_sensitive_text, sanitize_sensitive


AUTHORIZATION_ID = "FTG-P-VIDEO-003"
MODEL_ID = "seedance-2.0-fast-multi"
BASE_URL = "https://api.seedance.nz"
_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_API_KEY = re.compile(r"^sk-[A-Za-z0-9_-]{4,}$")
_PERCENT_PROGRESS = re.compile(r"^(?:0|[1-9][0-9]?|100)%$")
_SAFE_DIAGNOSTIC_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_SENSITIVE_DIAGNOSTIC_KEY = re.compile(
    r"(?i)(authorization|credential|api[_-]?key|token|secret|password|private[_-]?key|signature|sig)"
)
_VIDEO_STATUS = {
    "queued": ("running", "queued"),
    "not_start": ("running", "not_start"),
    "submitted": ("running", "submitted"),
    "in_progress": ("running", "in_progress"),
    "completed": ("succeeded", "completed"),
    "success": ("succeeded", "success"),
    "failed": ("failed", "failed"),
    "failure": ("failed", "failure"),
}


def _provider_summary(value: object, credential: str | None) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        value = value.replace(credential, "[REDACTED]") if credential else value
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    safe = sanitize_sensitive(value)
    if isinstance(safe, str):
        return safe[:1000]
    return json.dumps(safe, ensure_ascii=False, sort_keys=True)[:1000]


def _safe_https_uri(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
    )


def _safe_diagnostic_keys(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    return sorted(
        key
        for key in value
        if (
            isinstance(key, str)
            and _SAFE_DIAGNOSTIC_KEY.fullmatch(key) is not None
            and _SENSITIVE_DIAGNOSTIC_KEY.search(key) is None
        )
    )


def _safe_raw_status(value: object) -> str | None:
    if not isinstance(value, str) or contains_sensitive_text(value):
        return None
    return value[:256]


def _poll_diagnostic_summary(response: object, raw_status: object) -> str:
    nested = response.get("data") if isinstance(response, Mapping) else None
    return json.dumps(
        {
            "raw_status": _safe_raw_status(raw_status),
            "response_keys": _safe_diagnostic_keys(response),
            "nested_data_keys": _safe_diagnostic_keys(nested),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _poll_response_failure(message: str, response: object, raw_status: object = None) -> AdapterFailure:
    return AdapterFailure(
        "RESPONSE_INVALID",
        message,
        retryable=False,
        provider_error_summary=_poll_diagnostic_summary(response, raw_status),
    )


def _parse_video_progress(
    value: object,
    *,
    nested: bool,
    default: int | None,
    response: object,
    raw_status: object,
) -> int:
    if value is None:
        if default is not None:
            return default
        raise _poll_response_failure("Seedance.nz progress is invalid", response, raw_status)
    if isinstance(value, bool):
        raise _poll_response_failure("Seedance.nz progress is invalid", response, raw_status)
    if isinstance(value, int):
        progress = value
    elif nested and isinstance(value, str) and _PERCENT_PROGRESS.fullmatch(value) is not None:
        progress = int(value[:-1])
    else:
        raise _poll_response_failure("Seedance.nz progress is invalid", response, raw_status)
    if not 0 <= progress <= 100:
        raise _poll_response_failure("Seedance.nz progress is invalid", response, raw_status)
    return progress


def _video_result_uri(response: Mapping[str, object], nested: Mapping[str, object] | None) -> object:
    candidates: list[object] = []
    if nested is not None:
        candidates.append(nested.get("result_url"))
        nested_metadata = nested.get("metadata")
        candidates.append(nested_metadata.get("url") if isinstance(nested_metadata, Mapping) else None)
        nested_data = nested.get("data")
        content = nested_data.get("content") if isinstance(nested_data, Mapping) else None
        candidates.append(content.get("video_url") if isinstance(content, Mapping) else None)
    metadata = response.get("metadata")
    candidates.append(metadata.get("url") if isinstance(metadata, Mapping) else None)
    return next((candidate for candidate in candidates if _safe_https_uri(candidate)), None)


class SeedanceNzCredentialResolver:
    """Read the one authorized credential reference from the environment."""

    def __init__(self, *, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    def resolve(self) -> str:
        value = self._environ.get("SEEDANCE_NZ_API_KEY")
        if not isinstance(value, str) or _API_KEY.fullmatch(value) is None:
            raise AdapterFailure(
                "CREDENTIAL_UNAVAILABLE",
                "Seedance.nz credential environment reference is unavailable",
                retryable=False,
            )
        return value


class SeedanceNzHttpTransport(Protocol):
    def request_json(
        self,
        method: str,
        path: str,
        credential: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]: ...

    def download(self, uri: str) -> bytes: ...

    def upload_multipart(
        self,
        credential: str,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
    ) -> dict[str, object]: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class UrllibSeedanceNzHttpTransport:
    """Stdlib transport with fixed API origin and no credential redirects."""

    def __init__(self, *, timeout_seconds: float = 30.0, opener: object | None = None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener or build_opener(_NoRedirectHandler())
        self.network_calls = 0

    def request_json(
        self,
        method: str,
        path: str,
        credential: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        valid_target = (
            (method == "POST" and path == "/v1/videos")
            or (method == "GET" and re.fullmatch(r"/v1/videos/[A-Za-z0-9_-]{8,128}", path) is not None)
            or (method == "POST" and path == "/v1/image/generations")
            or (method == "GET" and re.fullmatch(r"/v1/image/generations/[A-Za-z0-9_-]{8,128}", path) is not None)
        )
        if not valid_target:
            raise AdapterFailure("REQUEST_INVALID", "Seedance.nz request target is invalid", retryable=False)
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            BASE_URL + path,
            data=body,
            method=method,
            headers={
                "Authorization": "Bearer " + credential,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        raw = self._open(request, credential=credential)
        return self._decode_json(raw, credential)

    def upload_multipart(
        self,
        credential: str,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
    ) -> dict[str, object]:
        if (
            not isinstance(file_name, str)
            or not file_name
            or '"' in file_name
            or "\r" in file_name
            or "\n" in file_name
            or not isinstance(file_bytes, bytes)
            or not file_bytes
            or not isinstance(media_type, str)
            or "\r" in media_type
            or "\n" in media_type
        ):
            raise AdapterFailure("UPLOAD_INVALID", "Seedance.nz upload input is invalid", retryable=False)
        boundary = "seedance-nz-" + hashlib.sha256(file_name.encode("utf-8") + b"\0" + file_bytes).hexdigest()[:24]
        body = b"".join((
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8"),
            f"Content-Type: {media_type}\r\n\r\n".encode("ascii"),
            file_bytes,
            f"\r\n--{boundary}--\r\n".encode("ascii"),
        ))
        request = Request(
            BASE_URL + "/v1/files/upload",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer " + credential,
                "Accept": "application/json",
                "Content-Type": "multipart/form-data; boundary=" + boundary,
            },
        )
        raw = self._open(request, credential=credential)
        return self._decode_json(raw, credential)

    def download(self, uri: str) -> bytes:
        if not _safe_https_uri(uri):
            raise AdapterFailure("DOWNLOAD_INVALID", "Seedance.nz artifact URL is invalid", retryable=False)
        request = Request(uri, method="GET", headers={"Accept": "video/mp4,image/*,*/*;q=0.5"})
        return self._open(request, credential=None)

    def _open(self, request: Request, *, credential: str | None) -> bytes:
        try:
            self.network_calls += 1
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            error.close()
            raise self._http_failure(error.code, raw, credential or "") from None
        except (URLError, TimeoutError, OSError):
            raise AdapterFailure(
                "NETWORK_ERROR",
                "Seedance.nz network request failed",
                retryable=False,
            ) from None
        if status != 200:
            raise self._http_failure(status, raw, credential or "")
        return raw

    @staticmethod
    def _decode_json(raw: bytes, credential: str) -> dict[str, object]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AdapterFailure(
                "RESPONSE_INVALID",
                "Seedance.nz returned malformed JSON",
                retryable=False,
                http_status=200,
                provider_error_summary=_provider_summary(raw, credential),
            ) from None
        if not isinstance(value, dict):
            raise AdapterFailure(
                "RESPONSE_INVALID",
                "Seedance.nz returned malformed JSON",
                retryable=False,
                http_status=200,
                provider_error_summary=_provider_summary(value, credential),
            )
        return value

    @staticmethod
    def _http_failure(status: int, raw: bytes, credential: str) -> AdapterFailure:
        code = "PROVIDER_FORBIDDEN" if status in {401, 403} else "rate_limited" if status == 429 else "HTTP_ERROR"
        return AdapterFailure(
            code,
            "Seedance.nz API rejected the request",
            retryable=False,
            http_status=status,
            provider_error_summary=_provider_summary(raw, credential),
        )


class SeedanceNzFileUploader:
    """Upload approved reference bytes to the documented temporary-file endpoint."""

    def __init__(
        self,
        *,
        transport: SeedanceNzHttpTransport | None = None,
        credential_resolver: SeedanceNzCredentialResolver | None = None,
    ) -> None:
        self._transport = transport or UrllibSeedanceNzHttpTransport()
        self._credential_resolver = credential_resolver or SeedanceNzCredentialResolver()
        self.network_calls = 0

    def upload(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
    ) -> dict[str, object]:
        if (
            not isinstance(file_name, str)
            or not file_name
            or "/" in file_name
            or "\\" in file_name
            or not isinstance(file_bytes, bytes)
            or not file_bytes
            or not isinstance(media_type, str)
            or not (media_type.startswith("image/") or media_type.startswith("video/"))
        ):
            raise AdapterFailure("UPLOAD_INVALID", "Seedance.nz upload input is invalid", retryable=False)
        credential = self._credential_resolver.resolve()
        try:
            self.network_calls += 1
            response = self._transport.upload_multipart(
                credential,
                file_name=file_name,
                file_bytes=file_bytes,
                media_type=media_type,
            )
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "Seedance.nz upload failed with no safe automatic retry",
                retryable=False,
                http_status=error.http_status,
                provider_error_summary=_provider_summary(error.provider_error_summary, credential),
            ) from None
        except Exception:
            raise AdapterFailure("UPLOAD_FAILED", "Seedance.nz upload failed unexpectedly", retryable=False) from None
        expected_type = "image" if media_type.startswith("image/") else "video"
        if not isinstance(response, Mapping):
            raise AdapterFailure("UPLOAD_RESPONSE_INVALID", "Seedance.nz upload metadata is invalid", retryable=False)
        url = response.get("url")
        size = response.get("size")
        expires_in = response.get("expires_in")
        if (
            not _safe_https_uri(url)
            or response.get("file_type") != expected_type
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size != len(file_bytes)
            or isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or not 1 <= expires_in <= 86400
        ):
            raise AdapterFailure("UPLOAD_RESPONSE_INVALID", "Seedance.nz upload metadata is invalid", retryable=False)
        return {
            "url": url,
            "file_type": expected_type,
            "size": size,
            "expires_in": expires_in,
        }


class FakeSeedanceNzFileUploader:
    """Deterministic reference uploader with no I/O or network seam."""

    execution_mode = "offline_adapter"
    network_performed = False
    network_calls = 0

    def upload(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
    ) -> dict[str, object]:
        if (
            not isinstance(file_name, str)
            or not file_name
            or not isinstance(file_bytes, bytes)
            or not file_bytes
            or not isinstance(media_type, str)
            or not (media_type.startswith("image/") or media_type.startswith("video/"))
        ):
            raise AdapterFailure("UPLOAD_INVALID", "Synthetic Seedance.nz upload input is invalid", retryable=False)
        file_type = "image" if media_type.startswith("image/") else "video"
        identity = hashlib.sha256(file_name.encode("utf-8") + b"\0" + file_bytes).hexdigest()[:24]
        return {
            "url": f"https://offline.invalid/seedance-nz/{identity}",
            "file_type": file_type,
            "size": len(file_bytes),
            "expires_in": 86400,
        }


class SeedanceNzVideoProviderAdapter:
    """Production adapter kept behind explicit dependency injection and authorization."""

    execution_mode = "seedance_nz_production"
    network_performed = True

    def __init__(
        self,
        *,
        transport: SeedanceNzHttpTransport | None = None,
        credential_resolver: SeedanceNzCredentialResolver | None = None,
        resolution: str = "480p",
        remaining_attempts: int = 1,
        timeout_seconds: float = 600.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not isinstance(resolution, str) or not resolution.strip():
            raise ValueError("resolution must be non-empty")
        if isinstance(remaining_attempts, bool) or not isinstance(remaining_attempts, int) or remaining_attempts < 1:
            raise ValueError("remaining_attempts must be positive")
        if timeout_seconds <= 0 or timeout_seconds > 600:
            raise ValueError("timeout_seconds must be within the authorized 600 second limit")
        self._transport = transport or UrllibSeedanceNzHttpTransport()
        self._credential_resolver = credential_resolver or SeedanceNzCredentialResolver()
        self._resolution = resolution
        self.remaining_attempts = remaining_attempts
        self._timeout_seconds = float(timeout_seconds)
        self._clock = clock
        self._started_at: dict[str, float] = {}
        self._completed: dict[str, dict[str, object]] = {}
        self._image_started_at: dict[str, float] = {}
        self._image_completed: dict[str, dict[str, object]] = {}
        self.network_calls = 0

    def submit(self, request: Mapping[str, object]) -> str:
        payload = self._submission_payload(request)
        credential = self._credential_resolver.resolve()
        if self.remaining_attempts <= 0:
            raise AdapterFailure(
                "PROVIDER_FORBIDDEN",
                "Seedance.nz submission attempt budget is exhausted",
                retryable=False,
            )
        self.remaining_attempts -= 1
        try:
            self.network_calls += 1
            response = self._transport.request_json(
                "POST",
                "/v1/videos",
                credential,
                payload=payload,
            )
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "Seedance.nz submission failed with no safe automatic retry",
                retryable=False,
                http_status=error.http_status,
                provider_error_summary=_provider_summary(error.provider_error_summary, credential),
            ) from None
        except Exception:
            raise AdapterFailure(
                "PROVIDER_FORBIDDEN",
                "Seedance.nz transport failed unexpectedly",
                retryable=False,
            ) from None
        task_id = response.get("task_id", response.get("id")) if isinstance(response, Mapping) else None
        task_id = self._validated_task_id(task_id, credential)
        self._started_at[task_id] = self._clock()
        return task_id

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        credential = self._credential_resolver.resolve()
        task_id = self._validated_task_id(provider_job_id, credential)
        started_at = self._started_at.get(task_id)
        if started_at is None:
            raise AdapterFailure("NOT_FOUND", "Seedance.nz task is absent", retryable=False)
        if self._clock() - started_at > self._timeout_seconds:
            raise AdapterFailure("TIMEOUT", "Seedance.nz task exceeded 600 seconds", retryable=False)
        try:
            self.network_calls += 1
            response = self._transport.request_json(
                "GET",
                f"/v1/videos/{task_id}",
                credential,
            )
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "Seedance.nz polling stopped after the first anomaly",
                retryable=False,
                http_status=error.http_status,
                provider_error_summary=_provider_summary(error.provider_error_summary, credential),
            ) from None
        except Exception:
            raise AdapterFailure(
                "PROVIDER_FORBIDDEN",
                "Seedance.nz polling transport failed unexpectedly",
                retryable=False,
            ) from None
        if not isinstance(response, Mapping):
            raise _poll_response_failure("Seedance.nz poll response is invalid", response)
        nested_data = response.get("data")
        if nested_data is not None and not isinstance(nested_data, Mapping):
            raise _poll_response_failure("Seedance.nz poll data is invalid", response)
        nested = nested_data if isinstance(nested_data, Mapping) else None
        status_source = (
            nested
            if nested is not None and "status" in nested
            else response
        )
        raw_status = status_source.get("status")
        if not isinstance(raw_status, str):
            raise _poll_response_failure("Seedance.nz poll status is invalid", response, raw_status)
        normalized = _VIDEO_STATUS.get(raw_status.casefold())
        if normalized is None:
            raise _poll_response_failure("Seedance.nz poll status is unsupported", response, raw_status)
        state, status = normalized
        default_progress = 0 if status in {"queued", "not_start", "submitted"} else 100 if state in {"succeeded", "failed"} else None
        progress = _parse_video_progress(
            status_source.get("progress"),
            nested=nested is not None,
            default=default_progress,
            response=response,
            raw_status=raw_status,
        )
        if state == "running":
            return {"state": state, "status": status, "progress": progress}
        if state == "failed":
            error = status_source.get("error")
            if not isinstance(error, Mapping):
                raise _poll_response_failure("Seedance.nz failure metadata is invalid", response, raw_status)
            code = error.get("code")
            message = error.get("message")
            if not isinstance(code, str) or not code or not isinstance(message, str):
                raise _poll_response_failure("Seedance.nz failure metadata is invalid", response, raw_status)
            return {
                "state": "failed",
                "status": status,
                "progress": 100,
                "error_code": code,
                "provider_error_summary": _provider_summary(error, credential),
                "refund_expected": True,
            }
        result_uri = _video_result_uri(response, nested)
        if not _safe_https_uri(result_uri):
            raise _poll_response_failure("Seedance.nz completion metadata is invalid", response, raw_status)
        late = self._clock() - started_at > self._timeout_seconds
        self._completed[task_id] = {
            "result_uri": result_uri,
            "late": late,
        }
        if late:
            raise AdapterFailure("TIMEOUT", "Seedance.nz completed after the deadline", retryable=False)
        return {"state": "succeeded", "status": status, "progress": 100}

    def cancel(self, provider_job_id: str) -> None:
        self._validated_task_id(provider_job_id)
        raise AdapterFailure(
            "CANCEL_NOT_SUPPORTED",
            "Seedance.nz does not document a cancellation endpoint",
            retryable=False,
        )

    def download(self, provider_job_id: str) -> Mapping[str, object]:
        task_id = self._validated_task_id(provider_job_id)
        completed = self._completed.get(task_id)
        if completed is None:
            raise AdapterFailure("DOWNLOAD_NOT_READY", "Seedance.nz task has no completed artifact", retryable=False)
        if completed.get("late") is True:
            raise AdapterFailure("LATE_ARTIFACT", "Seedance.nz late artifact cannot be downloaded", retryable=False)
        result_uri = completed.get("result_uri")
        if not _safe_https_uri(result_uri):
            raise AdapterFailure("DOWNLOAD_INVALID", "Seedance.nz artifact URL is invalid", retryable=False)
        try:
            self.network_calls += 1
            content = self._transport.download(str(result_uri))
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "Seedance.nz artifact download failed with no safe automatic retry",
                retryable=False,
                http_status=error.http_status,
                provider_error_summary=_provider_summary(error.provider_error_summary, None),
            ) from None
        except Exception:
            raise AdapterFailure(
                "DOWNLOAD_FAILED",
                "Seedance.nz artifact download failed unexpectedly",
                retryable=False,
            ) from None
        if not isinstance(content, bytes) or not content:
            raise AdapterFailure("DOWNLOAD_INVALID", "Seedance.nz artifact is empty", retryable=False)
        return {
            "content": content,
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "uri": f"memory://seedance-nz/{task_id}.mp4",
            "content_type": "video/mp4",
        }

    def submit_image(self, request: Mapping[str, object]) -> str:
        if not isinstance(request, Mapping):
            raise AdapterFailure("REQUEST_INVALID", "Seedance.nz image request is invalid", retryable=False)
        prompt = request.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or contains_sensitive_text(prompt):
            raise AdapterFailure("REQUEST_INVALID", "Seedance.nz image prompt is invalid", retryable=False)
        payload: dict[str, object] = {
            "model": "seedream-v5-pro-t2i",
            "prompt": prompt,
            "metadata": {"resolution": "1k", "output_format": "jpeg"},
        }
        images = request.get("images")
        if images is not None:
            if (
                not isinstance(images, list)
                or not 1 <= len(images) <= 10
                or any(not _safe_https_uri(image) for image in images)
            ):
                raise AdapterFailure("REQUEST_INVALID", "Seedance.nz image references are invalid", retryable=False)
            payload["model"] = "seedream-v5-pro-i2i"
            payload["images"] = list(images)
        credential = self._credential_resolver.resolve()
        if self.remaining_attempts <= 0:
            raise AdapterFailure(
                "PROVIDER_FORBIDDEN",
                "Seedance.nz submission attempt budget is exhausted",
                retryable=False,
            )
        self.remaining_attempts -= 1
        try:
            self.network_calls += 1
            response = self._transport.request_json(
                "POST",
                "/v1/image/generations",
                credential,
                payload=payload,
            )
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "Seedance.nz image submission failed with no safe automatic retry",
                retryable=False,
                http_status=error.http_status,
                provider_error_summary=_provider_summary(error.provider_error_summary, credential),
            ) from None
        except Exception:
            raise AdapterFailure(
                "PROVIDER_FORBIDDEN",
                "Seedance.nz image transport failed unexpectedly",
                retryable=False,
            ) from None
        task_id = response.get("id") if isinstance(response, Mapping) else None
        task_id = self._validated_task_id(task_id, credential)
        self._image_started_at[task_id] = self._clock()
        return task_id

    def poll_image(self, provider_job_id: str) -> Mapping[str, object]:
        credential = self._credential_resolver.resolve()
        task_id = self._validated_task_id(provider_job_id, credential)
        started_at = self._image_started_at.get(task_id)
        if started_at is None:
            raise AdapterFailure("NOT_FOUND", "Seedance.nz image task is absent", retryable=False)
        if self._clock() - started_at > self._timeout_seconds:
            raise AdapterFailure("TIMEOUT", "Seedance.nz image task exceeded 600 seconds", retryable=False)
        try:
            self.network_calls += 1
            response = self._transport.request_json(
                "GET",
                f"/v1/image/generations/{task_id}",
                credential,
            )
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "Seedance.nz image polling stopped after the first anomaly",
                retryable=False,
                http_status=error.http_status,
                provider_error_summary=_provider_summary(error.provider_error_summary, credential),
            ) from None
        except Exception:
            raise AdapterFailure(
                "PROVIDER_FORBIDDEN",
                "Seedance.nz image polling transport failed unexpectedly",
                retryable=False,
            ) from None
        if not isinstance(response, Mapping) or response.get("code") != "success":
            raise AdapterFailure("RESPONSE_INVALID", "Seedance.nz image poll response is invalid", retryable=False)
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise AdapterFailure("RESPONSE_INVALID", "Seedance.nz image poll data is invalid", retryable=False)
        status = data.get("status")
        if status not in {"NOT_START", "SUBMITTED", "IN_PROGRESS", "SUCCESS", "FAILURE"}:
            raise AdapterFailure("RESPONSE_INVALID", "Seedance.nz image status is unsupported", retryable=False)
        if status in {"NOT_START", "SUBMITTED", "IN_PROGRESS"}:
            return {"code": "success", "data": {"status": status}}
        if status == "FAILURE":
            error = data.get("error")
            result = {"code": "success", "data": {"status": status}}
            if isinstance(error, Mapping):
                result["data"] = {"status": status, "error": dict(error)}
            return result
        result_url = data.get("result_url")
        if not _safe_https_uri(result_url):
            nested = data.get("data")
            content = nested.get("content") if isinstance(nested, Mapping) else None
            result_url = content.get("image_url") if isinstance(content, Mapping) else None
        if not _safe_https_uri(result_url):
            raise AdapterFailure("RESPONSE_INVALID", "Seedance.nz image result URL is invalid", retryable=False)
        late = self._clock() - started_at > self._timeout_seconds
        self._image_completed[task_id] = {"result_uri": result_url, "late": late}
        if late:
            raise AdapterFailure("TIMEOUT", "Seedance.nz image completed after the deadline", retryable=False)
        return {"code": "success", "data": {"status": status, "result_url": result_url}}

    def download_image(self, provider_job_id: str) -> Mapping[str, object]:
        task_id = self._validated_task_id(provider_job_id)
        completed = self._image_completed.get(task_id)
        if completed is None:
            raise AdapterFailure("DOWNLOAD_NOT_READY", "Seedance.nz image has no completed artifact", retryable=False)
        if completed.get("late") is True:
            raise AdapterFailure("LATE_ARTIFACT", "Seedance.nz late image cannot be downloaded", retryable=False)
        result_uri = completed.get("result_uri")
        if not _safe_https_uri(result_uri):
            raise AdapterFailure("DOWNLOAD_INVALID", "Seedance.nz image URL is invalid", retryable=False)
        try:
            self.network_calls += 1
            content = self._transport.download(str(result_uri))
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "Seedance.nz image download failed with no safe automatic retry",
                retryable=False,
                http_status=error.http_status,
                provider_error_summary=_provider_summary(error.provider_error_summary, None),
            ) from None
        except Exception:
            raise AdapterFailure("DOWNLOAD_FAILED", "Seedance.nz image download failed unexpectedly", retryable=False) from None
        if not isinstance(content, bytes) or not content:
            raise AdapterFailure("DOWNLOAD_INVALID", "Seedance.nz image artifact is empty", retryable=False)
        return {
            "bytes": content,
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "uri": f"memory://seedance-nz/{task_id}.jpeg",
            "content_type": "image/jpeg",
        }

    def _submission_payload(self, request: Mapping[str, object]) -> dict[str, object]:
        output = request.get("output", request)
        if not isinstance(output, Mapping):
            raise AdapterFailure("REQUEST_INVALID", "Seedance.nz output must be an object", retryable=False)
        prompt = output.get("prompt")
        seconds = output.get("seconds")
        metadata = output.get("metadata")
        content = metadata.get("content") if isinstance(metadata, Mapping) else output.get("content")
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or contains_sensitive_text(prompt)
            or isinstance(seconds, bool)
            or not isinstance(seconds, (int, str))
            or not str(seconds).isdigit()
            or not 1 <= int(str(seconds)) <= 15
            or not isinstance(content, list)
            or not content
        ):
            raise AdapterFailure("REQUEST_INVALID", "Seedance.nz output is invalid", retryable=False)
        normalized: list[dict[str, object]] = []
        for item in content:
            if not isinstance(item, Mapping) or item.get("type") not in {"image_url", "video_url"}:
                raise AdapterFailure("REQUEST_INVALID", "Seedance.nz content item is invalid", retryable=False)
            kind = str(item["type"])
            nested = item.get(kind)
            if not isinstance(nested, Mapping) or set(nested) != {"url"} or not _safe_https_uri(nested.get("url")):
                raise AdapterFailure("REQUEST_INVALID", "Seedance.nz content URL is invalid", retryable=False)
            normalized.append({"type": kind, kind: {"url": nested["url"]}})
        return {
            "model": MODEL_ID,
            "prompt": prompt,
            "seconds": str(seconds),
            "metadata": {"resolution": self._resolution, "content": normalized},
        }

    @staticmethod
    def _validated_task_id(raw: object, credential: str | None = None) -> str:
        if (
            not isinstance(raw, str)
            or _TASK_ID.fullmatch(raw) is None
            or contains_sensitive_text(raw)
            or (credential is not None and raw == credential)
        ):
            raise AdapterFailure(
                "RESPONSE_INVALID",
                "Seedance.nz returned an invalid task identity",
                retryable=False,
            )
        return raw


class FakeSeedanceNzVideoProviderAdapter:
    """Deterministic in-memory Seedance.nz protocol implementation."""

    execution_mode = "offline_adapter"
    network_performed = False

    def __init__(
        self,
        *,
        poll_statuses: tuple[str, ...] = ("queued", "in_progress", "completed"),
        submit_failures: int = 0,
        poll_failures: int = 0,
        corrupt_download: bool = False,
        artifact_content: bytes = b"synthetic-mp4",
        artifact_content_type: str = "video/mp4",
        image_poll_statuses: tuple[str, ...] = ("SUBMITTED", "IN_PROGRESS", "SUCCESS"),
        image_content: bytes = b"synthetic-jpeg",
    ) -> None:
        if not poll_statuses or any(
            status not in {"queued", "in_progress", "completed", "failed"}
            for status in poll_statuses
        ):
            raise ValueError("poll_statuses contains an unsupported status")
        self._poll_statuses = poll_statuses
        self._remaining_submit_failures = submit_failures
        self._remaining_poll_failures = poll_failures
        self._corrupt_download = corrupt_download
        self._artifact_content = bytes(artifact_content)
        self._artifact_content_type = artifact_content_type
        if not image_poll_statuses or any(
            status not in {"NOT_START", "SUBMITTED", "IN_PROGRESS", "SUCCESS", "FAILURE"}
            for status in image_poll_statuses
        ):
            raise ValueError("image_poll_statuses contains an unsupported status")
        self._image_poll_statuses = image_poll_statuses
        self._image_content = bytes(image_content)
        self._jobs: dict[str, dict[str, object]] = {}
        self._image_jobs: dict[str, dict[str, object]] = {}
        self.network_calls = 0

    def submit(self, request: Mapping[str, object]) -> str:
        if self._remaining_submit_failures:
            self._remaining_submit_failures -= 1
            raise AdapterFailure(
                "PROVIDER_FORBIDDEN",
                "Synthetic Seedance.nz submission failed",
                retryable=False,
            )
        identity = str(request.get("request_hash", "")) + str(request.get("idempotency_key", ""))
        provider_job_id = "fake-sd-nz-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        self._jobs.setdefault(provider_job_id, {"poll_index": 0, "completed": False})
        return provider_job_id

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        job = self._job(provider_job_id)
        if self._remaining_poll_failures:
            self._remaining_poll_failures -= 1
            raise AdapterFailure(
                "PROVIDER_FORBIDDEN",
                "Synthetic Seedance.nz polling failed",
                retryable=False,
            )
        index = int(job["poll_index"])
        status = self._poll_statuses[min(index, len(self._poll_statuses) - 1)]
        job["poll_index"] = index + 1
        progress = 0 if status == "queued" else 50 if status == "in_progress" else 100
        if status == "completed":
            job["completed"] = True
            return {"state": "succeeded", "status": status, "progress": progress}
        if status == "failed":
            return {
                "state": "failed",
                "status": status,
                "progress": progress,
                "provider_error_summary": "Synthetic Seedance.nz failure",
            }
        return {"state": "running", "status": status, "progress": progress}

    def cancel(self, provider_job_id: str) -> None:
        self._job(provider_job_id)
        raise AdapterFailure(
            "CANCEL_NOT_SUPPORTED",
            "Seedance.nz does not document a cancellation endpoint",
            retryable=False,
        )

    def download(self, provider_job_id: str) -> Mapping[str, object]:
        job = self._job(provider_job_id)
        if job["completed"] is not True:
            raise AdapterFailure(
                "DOWNLOAD_NOT_READY",
                "Seedance.nz artifact is not completed",
                retryable=False,
            )
        content = self._artifact_content
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if self._corrupt_download:
            digest = "sha256:" + "0" * 64
        return {
            "content": content,
            "sha256": digest,
            "uri": f"memory://seedance-nz/{provider_job_id}.mp4",
            "content_type": self._artifact_content_type,
        }

    def _job(self, provider_job_id: str) -> dict[str, object]:
        try:
            return self._jobs[provider_job_id]
        except KeyError:
            raise AdapterFailure(
                "NOT_FOUND",
                "Seedance.nz task is absent",
                retryable=False,
            ) from None

    def submit_image(self, request: Mapping[str, object]) -> str:
        identity = json.dumps(dict(request), sort_keys=True, separators=(",", ":"))
        provider_job_id = "fake-sd-nz-img-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        self._image_jobs.setdefault(provider_job_id, {"poll_index": 0, "completed": False})
        return provider_job_id

    def poll_image(self, provider_job_id: str) -> Mapping[str, object]:
        try:
            job = self._image_jobs[provider_job_id]
        except KeyError:
            raise AdapterFailure("NOT_FOUND", "Seedance.nz image task is absent", retryable=False) from None
        index = int(job["poll_index"])
        status = self._image_poll_statuses[min(index, len(self._image_poll_statuses) - 1)]
        job["poll_index"] = index + 1
        data: dict[str, object] = {"task_id": provider_job_id, "status": status}
        if status == "SUCCESS":
            job["completed"] = True
            data["result_url"] = f"fake://{provider_job_id}.jpeg"
        elif status == "FAILURE":
            data["error"] = {"code": "synthetic_failure", "message": "Synthetic Seedance.nz failure"}
        return {"code": "success", "data": data}

    def download_image(self, provider_job_id: str) -> Mapping[str, object]:
        try:
            job = self._image_jobs[provider_job_id]
        except KeyError:
            raise AdapterFailure("NOT_FOUND", "Seedance.nz image task is absent", retryable=False) from None
        if job["completed"] is not True:
            raise AdapterFailure("DOWNLOAD_NOT_READY", "Seedance.nz image is not completed", retryable=False)
        content = self._image_content
        return {
            "bytes": content,
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "uri": f"memory://seedance-nz/{provider_job_id}.jpeg",
            "content_type": "image/jpeg",
        }
