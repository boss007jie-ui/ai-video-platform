"""Explicit KIE production adapter for the authorized Seedance smoke path."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Protocol
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .adapters import AdapterFailure
from .errors import contains_sensitive_text, sanitize_sensitive


KIE_MODEL_ID = "bytedance/seedance-2-fast"
KIE_DOWNLOAD_MAX_ATTEMPTS = 2
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Accept-Encoding": "identity",
    "Origin": "https://kieai.redpandaai.co",
    "Referer": "https://kieai.redpandaai.co/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Ch-Ua": '"Chromium";v="126", "Not.A/Brand";v="24", "Google Chrome";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}
ARTIFACT_DOWNLOAD_HEADERS = {
    "User-Agent": BROWSER_HEADERS["User-Agent"],
    "Accept": "video/mp4,video/*;q=0.9,application/octet-stream;q=0.8,*/*;q=0.5",
    "Accept-Language": BROWSER_HEADERS["Accept-Language"],
    "Accept-Encoding": "identity",
    "Referer": "https://kie.ai/",
    "Sec-Fetch-Dest": "video",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Ch-Ua": BROWSER_HEADERS["Sec-Ch-Ua"],
    "Sec-Ch-Ua-Mobile": BROWSER_HEADERS["Sec-Ch-Ua-Mobile"],
    "Sec-Ch-Ua-Platform": BROWSER_HEADERS["Sec-Ch-Ua-Platform"],
}


def _provider_diagnostic_summary(value: object, *, credential: str | None = None) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace").strip()
    if isinstance(value, str):
        text = value.replace(credential, "[REDACTED]") if credential else value
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = text
    safe = sanitize_sensitive(value)
    if isinstance(safe, str):
        return safe[:1000] or "Provider returned an empty error body"
    return json.dumps(safe, ensure_ascii=False, sort_keys=True)[:1000]
_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_OUTPUT_FIELDS = {
    "format",
    "prompt",
    "reference_image_urls",
    "resolution",
    "aspect_ratio",
    "duration",
    "return_last_frame",
    "generate_audio",
    "web_search",
}


class KieCredentialResolver:
    """Resolve the one authorized credential without logging or persistence."""

    def __init__(self, *, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    def resolve(self) -> str:
        value = self._environ.get("KIE_API_KEY")
        if not isinstance(value, str) or not value.strip():
            raise AdapterFailure(
                "CREDENTIAL_UNAVAILABLE",
                "KIE credential environment reference is unavailable",
                retryable=False,
            )
        return value


class KieHttpTransport(Protocol):
    def request_json(
        self,
        method: str,
        path: str,
        credential: str,
        *,
        payload: dict[str, object] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, object]: ...

    def download(self, uri: str) -> bytes: ...

    def upload_multipart(
        self,
        credential: str,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
        upload_path: str,
    ) -> dict[str, object]: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class UrllibKieHttpTransport:
    """Small stdlib HTTP transport; authentication is sent only to api.kie.ai."""

    _BASE_URL = "https://api.kie.ai"
    _UPLOAD_BASE_URL = "https://kieai.redpandaai.co"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds
        self._api_opener = build_opener(_NoRedirectHandler())
        self._upload_opener = build_opener(_NoRedirectHandler())
        self.http_status_chain: list[int] = []

    def request_json(
        self,
        method: str,
        path: str,
        credential: str,
        *,
        payload: dict[str, object] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, object]:
        if method not in {"GET", "POST"} or not path.startswith("/api/"):
            raise AdapterFailure("KIE_REQUEST_INVALID", "KIE request target is invalid", retryable=False)
        suffix = "?" + urlencode(query) if query else ""
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            self._BASE_URL + path + suffix,
            data=body,
            method=method,
            headers={
                "Authorization": "Bearer " + credential,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with self._api_opener.open(request, timeout=self._timeout_seconds) as response:
                self.http_status_chain.append(int(getattr(response, "status", 200)))
                raw = response.read()
        except HTTPError as error:
            self.http_status_chain.append(error.code)
            retryable = error.code == 429 or error.code >= 500
            summary = self._provider_error_summary(error.read(), credential)
            raise AdapterFailure(
                "KIE_HTTP_ERROR",
                "KIE API rejected the request",
                retryable=retryable,
                http_status=error.code,
                provider_error_summary=summary,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise AdapterFailure("KIE_NETWORK_ERROR", "KIE API network request failed", retryable=True) from None
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE API returned malformed JSON",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_error_summary(raw, credential),
            ) from None
        if not isinstance(decoded, dict):
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE API returned malformed JSON",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_error_summary(raw, credential),
            )
        return decoded

    def download(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise AdapterFailure("KIE_DOWNLOAD_INVALID", "KIE artifact URL is invalid", retryable=False)
        request = Request(uri, method="GET", headers=ARTIFACT_DOWNLOAD_HEADERS)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                self.http_status_chain.append(int(getattr(response, "status", 200)))
                return response.read()
        except HTTPError as error:
            self.http_status_chain.append(error.code)
            retryable = error.code == 429 or error.code >= 500
            raise AdapterFailure(
                "KIE_DOWNLOAD_ERROR",
                "KIE artifact download failed",
                retryable=retryable,
                http_status=error.code,
                provider_error_summary=_provider_diagnostic_summary(error.read()),
            ) from None
        except (URLError, TimeoutError, OSError):
            raise AdapterFailure("KIE_DOWNLOAD_ERROR", "KIE artifact download failed", retryable=True) from None

    def upload_multipart(
        self,
        credential: str,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
        upload_path: str,
    ) -> dict[str, object]:
        body, content_type = self._multipart_body(
            file_name=file_name,
            file_bytes=file_bytes,
            media_type=media_type,
            upload_path=upload_path,
        )
        request = Request(
            self._UPLOAD_BASE_URL + "/api/file-stream-upload",
            data=body,
            method="POST",
            headers={
                **BROWSER_HEADERS,
                "Authorization": "Bearer " + credential,
                "Content-Type": content_type,
            },
        )
        try:
            with self._upload_opener.open(request, timeout=self._timeout_seconds) as response:
                self.http_status_chain.append(int(getattr(response, "status", 200)))
                raw = response.read()
        except HTTPError as error:
            self.http_status_chain.append(error.code)
            retryable = error.code == 429 or error.code >= 500
            summary = self._provider_error_summary(error.read(), credential)
            raise AdapterFailure(
                "KIE_UPLOAD_ERROR",
                "KIE reference upload failed",
                retryable=retryable,
                http_status=error.code,
                provider_error_summary=summary,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise AdapterFailure("KIE_UPLOAD_ERROR", "KIE reference upload failed", retryable=True) from None
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AdapterFailure(
                "KIE_UPLOAD_INVALID",
                "KIE reference upload returned malformed JSON",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_error_summary(raw, credential),
            ) from None
        if not isinstance(decoded, dict):
            raise AdapterFailure(
                "KIE_UPLOAD_INVALID",
                "KIE reference upload returned malformed JSON",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_error_summary(raw, credential),
            )
        return decoded

    @staticmethod
    def _multipart_body(
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
        upload_path: str,
    ) -> tuple[bytes, str]:
        boundary = "----ai-video-platform-kie-" + uuid.uuid4().hex
        body = bytearray()
        fields = (
            ("file", file_name, file_bytes, media_type),
            ("uploadPath", None, upload_path.encode("utf-8"), None),
            ("fileName", None, file_name.encode("utf-8"), None),
        )
        for name, filename, value, field_media_type in fields:
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            if filename is None:
                body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
            else:
                body.extend(
                    (
                        f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                        f"Content-Type: {field_media_type}\r\n\r\n"
                    ).encode("ascii")
                )
            body.extend(value)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("ascii"))
        return bytes(body), f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _provider_error_summary(raw: bytes, credential: str) -> str:
        return _provider_diagnostic_summary(raw, credential=credential)


class KieReferenceImageUploader:
    """Upload approved small local images without exposing credential material."""

    _MAX_BYTES = 1024 * 1024
    _MIME_TYPES = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }

    def __init__(
        self,
        *,
        transport: KieHttpTransport | None = None,
        credential_resolver: KieCredentialResolver | None = None,
    ) -> None:
        self._transport = transport or UrllibKieHttpTransport()
        self._credential_resolver = credential_resolver or KieCredentialResolver()

    def upload(self, path: str | Path, *, expected_sha256: str) -> str:
        image_path = Path(path)
        suffix = image_path.suffix.lower()
        if suffix not in self._MIME_TYPES or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_sha256) is None:
            raise AdapterFailure("KIE_UPLOAD_INVALID", "KIE reference image metadata is invalid", retryable=False)
        try:
            content = image_path.read_bytes()
        except OSError:
            raise AdapterFailure("KIE_UPLOAD_INVALID", "KIE reference image is unavailable", retryable=False) from None
        if not content or len(content) > self._MAX_BYTES:
            raise AdapterFailure("KIE_UPLOAD_INVALID", "KIE reference image size is invalid", retryable=False)
        actual_sha256 = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual_sha256 != expected_sha256:
            raise AdapterFailure("KIE_UPLOAD_INVALID", "KIE reference image digest mismatch", retryable=False)
        credential = self._credential_resolver.resolve()
        try:
            response = self._transport.upload_multipart(
                credential,
                file_name=actual_sha256.removeprefix("sha256:")[:24] + suffix,
                file_bytes=content,
                media_type=self._MIME_TYPES[suffix],
                upload_path="ftg-p-video-001",
            )
        except AdapterFailure:
            raise
        except Exception:
            raise AdapterFailure("KIE_UPLOAD_ERROR", "KIE reference upload failed unexpectedly", retryable=False) from None
        if response.get("code") != 200 or not isinstance(response.get("data"), Mapping):
            raise AdapterFailure(
                "KIE_UPLOAD_INVALID",
                "KIE reference upload returned an unsuccessful response",
                retryable=False,
                http_status=200,
                provider_error_summary=_provider_diagnostic_summary(response, credential=credential),
            )
        data = response["data"]
        candidates = [data.get("downloadUrl"), data.get("fileUrl")]
        if isinstance(data.get("filePath"), str):
            candidates.append("https://tempfile.redpandaai.co/" + data["filePath"].lstrip("/"))
        uri = next((candidate for candidate in candidates if KieVideoProviderAdapter._safe_https_uri(candidate)), None)
        if uri is None:
            raise AdapterFailure(
                "KIE_UPLOAD_INVALID",
                "KIE reference upload returned an invalid URL",
                retryable=False,
                http_status=200,
                provider_error_summary=_provider_diagnostic_summary(response, credential=credential),
            )
        return str(uri)


class KieVideoProviderAdapter:
    """KIE adapter with the signed Seedance smoke limits enforced before network access."""

    execution_mode = "kie_production"
    network_performed = True

    def __init__(
        self,
        *,
        transport: KieHttpTransport | None = None,
        credential_resolver: KieCredentialResolver | None = None,
    ) -> None:
        self._transport = transport or UrllibKieHttpTransport()
        self._credential_resolver = credential_resolver or KieCredentialResolver()
        self._completed: dict[str, dict[str, object]] = {}
        self.download_http_status_chain: list[int] = []
        self.download_attempts: list[dict[str, object]] = []

    def submit(self, request: Mapping[str, object]) -> str:
        payload = self._submission_payload(request)
        try:
            response = self._request_json("POST", "/api/v1/jobs/createTask", payload=payload)
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "KIE submission failed with no safe automatic retry",
                retryable=False,
                http_status=error.http_status,
                provider_error_summary=error.provider_error_summary,
            ) from None
        data = self._success_data(response)
        task_id = data.get("taskId")
        if (
            not isinstance(task_id, str)
            or _TASK_ID.fullmatch(task_id) is None
            or contains_sensitive_text(task_id)
            or task_id == self._credential_resolver.resolve()
        ):
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE API returned an invalid task identity",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_summary(data),
            )
        return task_id

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        task_id = self._validated_task_id(provider_job_id)
        try:
            response = self._request_json(
                "GET",
                "/api/v1/jobs/recordInfo",
                query={"taskId": task_id},
            )
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "KIE polling stopped after the first anomaly",
                retryable=False,
                http_status=error.http_status,
                provider_error_summary=error.provider_error_summary,
            ) from None
        data = self._success_data(response)
        if data.get("taskId") != task_id or data.get("model") not in {None, KIE_MODEL_ID}:
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE task response identity is invalid",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_summary(data),
            )
        state = data.get("state")
        mapped = {
            "waiting": "running",
            "queuing": "running",
            "generating": "running",
            "success": "succeeded",
            "fail": "failed",
        }.get(state)
        if mapped is None:
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE task state is unsupported",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_summary(data),
            )
        result: dict[str, object] = {"state": mapped}
        cost = data.get("creditsConsumed")
        if cost is not None:
            if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
                raise AdapterFailure(
                    "KIE_RESPONSE_INVALID",
                    "KIE task cost is invalid",
                    retryable=False,
                    http_status=200,
                    provider_error_summary=self._provider_summary(data),
                )
            result["cost_units"] = cost
        if mapped == "succeeded":
            result_uri = self._result_uri(data.get("resultJson"))
            self._completed[task_id] = {"result_uri": result_uri, **result}
        elif mapped == "failed":
            result["http_status"] = 200
            result["provider_error_summary"] = self._provider_summary(data)
        return result

    def cancel(self, provider_job_id: str) -> None:
        self._validated_task_id(provider_job_id)
        raise AdapterFailure(
            "KIE_CANCEL_UNAVAILABLE",
            "KIE Market API does not expose a documented cancellation endpoint",
            retryable=False,
        )

    def download(self, provider_job_id: str) -> Mapping[str, object]:
        task_id = self._validated_task_id(provider_job_id)
        completed = self._completed.get(task_id)
        if completed is None:
            raise AdapterFailure("KIE_DOWNLOAD_INVALID", "KIE task has no completed artifact", retryable=False)
        self.download_http_status_chain = []
        self.download_attempts = []
        content: bytes | None = None
        for attempt in range(1, KIE_DOWNLOAD_MAX_ATTEMPTS + 1):
            before_refresh = self._transport_status_count()
            try:
                result_uri = self._refresh_result_uri(task_id)
            except AdapterFailure as error:
                refresh_statuses = self._transport_statuses_since(before_refresh)
                self.download_http_status_chain.extend(refresh_statuses)
                self.download_attempts.append({
                    "attempt": attempt,
                    "refresh_http_status": refresh_statuses[-1] if refresh_statuses else error.http_status,
                    "download_http_status": None,
                    "outcome": "failed",
                    "retry_reason": "TASK_DETAIL_REFRESH_FAILED",
                })
                raise AdapterFailure(
                    error.code,
                    str(error),
                    retryable=False,
                    http_status=error.http_status,
                    provider_error_summary=error.provider_error_summary,
                    download_http_status_chain=self.download_http_status_chain,
                    download_attempts=self.download_attempts,
                ) from None
            refresh_statuses = self._transport_statuses_since(before_refresh)
            self.download_http_status_chain.extend(refresh_statuses)
            before_download = self._transport_status_count()
            try:
                content = self._download(result_uri)
            except AdapterFailure as error:
                download_statuses = self._transport_statuses_since(before_download)
                self.download_http_status_chain.extend(download_statuses)
                reason = self._download_retry_reason(error)
                will_retry = reason is not None and attempt < KIE_DOWNLOAD_MAX_ATTEMPTS
                self.download_attempts.append({
                    "attempt": attempt,
                    "refresh_http_status": refresh_statuses[-1] if refresh_statuses else 200,
                    "download_http_status": download_statuses[-1] if download_statuses else error.http_status,
                    "outcome": "retry" if will_retry else "failed",
                    "retry_reason": reason if will_retry else ("EXHAUSTED_" + reason if reason else "NON_RETRYABLE_DOWNLOAD_FAILURE"),
                })
                if will_retry:
                    continue
                raise AdapterFailure(
                    error.code,
                    "KIE artifact download retry budget is exhausted" if reason else str(error),
                    retryable=False,
                    http_status=error.http_status,
                    provider_error_summary=error.provider_error_summary,
                    download_http_status_chain=self.download_http_status_chain,
                    download_attempts=self.download_attempts,
                ) from None
            download_statuses = self._transport_statuses_since(before_download)
            self.download_http_status_chain.extend(download_statuses)
            self.download_attempts.append({
                "attempt": attempt,
                "refresh_http_status": refresh_statuses[-1] if refresh_statuses else 200,
                "download_http_status": download_statuses[-1] if download_statuses else 200,
                "outcome": "success",
                "retry_reason": None,
            })
            break
        if content is None:
            raise AdapterFailure("KIE_DOWNLOAD_ERROR", "KIE artifact download retry budget is exhausted", retryable=False)
        if not content:
            raise AdapterFailure(
                "KIE_DOWNLOAD_INVALID",
                "KIE artifact is empty",
                retryable=False,
                http_status=200,
                provider_error_summary="Provider returned an empty artifact body",
            )
        return {
            "content": content,
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "uri": f"kie://{task_id}/video.mp4",
            "content_type": "video/mp4",
            "download_http_status_chain": list(self.download_http_status_chain),
            "download_attempts": [dict(item) for item in self.download_attempts],
        }

    def _refresh_result_uri(self, task_id: str) -> str:
        response = self._request_json(
            "GET",
            "/api/v1/jobs/recordInfo",
            query={"taskId": task_id},
        )
        data = self._success_data(response)
        if (
            data.get("taskId") != task_id
            or data.get("model") not in {None, KIE_MODEL_ID}
            or data.get("state") != "success"
        ):
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE refreshed task result is invalid",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_summary(data),
            )
        result_uri = self._result_uri(data.get("resultJson"))
        self._completed[task_id] = {**self._completed[task_id], "result_uri": result_uri}
        return result_uri

    def _transport_status_count(self) -> int:
        chain = getattr(self._transport, "http_status_chain", None)
        return len(chain) if isinstance(chain, list) else 0

    def _transport_statuses_since(self, index: int) -> list[int]:
        chain = getattr(self._transport, "http_status_chain", None)
        if not isinstance(chain, list):
            return []
        return [int(status) for status in chain[index:] if isinstance(status, int)]

    @staticmethod
    def _download_retry_reason(error: AdapterFailure) -> str | None:
        status = error.http_status
        if status == 403 or status == 429 or (isinstance(status, int) and status >= 500):
            return f"HTTP_{status}_REFRESH_RESULT_URL"
        if error.retryable and status is None:
            return "NETWORK_OR_TIMEOUT_REFRESH_RESULT_URL"
        return None

    def _submission_payload(self, request: Mapping[str, object]) -> dict[str, object]:
        binding = request.get("provider_binding")
        budget = request.get("budget")
        output = request.get("output")
        if not isinstance(binding, Mapping) or binding.get("provider_id") != "kie" or binding.get("model_id") != KIE_MODEL_ID:
            raise AdapterFailure("KIE_GUARDRAIL", "KIE provider binding is not authorized", retryable=False)
        if not isinstance(budget, Mapping) or any(
            budget.get(field) != expected
            for field, expected in (("max_requests", 1), ("max_concurrency", 1), ("max_attempts", 2))
        ):
            raise AdapterFailure("KIE_GUARDRAIL", "KIE smoke budget guardrail is invalid", retryable=False)
        if budget.get("timeout_seconds") not in {600, 1800}:
            raise AdapterFailure("KIE_GUARDRAIL", "KIE smoke timeout guardrail is invalid", retryable=False)
        if not isinstance(output, Mapping) or set(output) != _OUTPUT_FIELDS:
            raise AdapterFailure("KIE_GUARDRAIL", "KIE output configuration is invalid", retryable=False)
        prompt = output.get("prompt")
        references = output.get("reference_image_urls")
        duration = output.get("duration")
        if (
            output.get("format") != "mp4"
            or output.get("resolution") != "480p"
            or output.get("aspect_ratio") != "16:9"
            or isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration < 1
            or duration > 6
            or output.get("return_last_frame") is not False
            or output.get("generate_audio") is not False
            or output.get("web_search") is not False
            or not isinstance(prompt, str)
            or not prompt.strip()
            or contains_sensitive_text(prompt)
            or not isinstance(references, list)
            or len(references) < 2
            or any(not self._safe_https_uri(uri) for uri in references)
        ):
            raise AdapterFailure("KIE_GUARDRAIL", "KIE smoke output exceeds the authorized envelope", retryable=False)
        return {
            "model": KIE_MODEL_ID,
            "input": {
                "prompt": prompt,
                "reference_image_urls": list(references),
                "return_last_frame": False,
                "generate_audio": False,
                "resolution": "480p",
                "aspect_ratio": "16:9",
                "duration": duration,
                "web_search": False,
            },
        }

    def _request_json(self, method: str, path: str, **kwargs: object) -> dict[str, object]:
        try:
            return self._transport.request_json(
                method,
                path,
                self._credential_resolver.resolve(),
                **kwargs,
            )
        except AdapterFailure:
            raise
        except Exception:
            raise AdapterFailure("KIE_NETWORK_ERROR", "KIE transport failed unexpectedly", retryable=False) from None

    def _download(self, uri: str) -> bytes:
        try:
            return self._transport.download(uri)
        except AdapterFailure:
            raise
        except Exception:
            raise AdapterFailure("KIE_DOWNLOAD_ERROR", "KIE artifact download failed unexpectedly", retryable=False) from None

    def _success_data(self, response: object) -> dict[str, object]:
        if not isinstance(response, Mapping) or response.get("code") != 200 or not isinstance(response.get("data"), Mapping):
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE API returned an unsuccessful response",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_summary(response),
            )
        return dict(response["data"])

    def _provider_summary(self, response: object) -> str:
        return _provider_diagnostic_summary(response, credential=self._credential_resolver.resolve())

    def _result_uri(self, raw: object) -> str:
        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE result metadata is malformed",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_summary(raw),
            ) from None
        if not isinstance(result, Mapping):
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE result metadata is malformed",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_summary(raw),
            )
        urls = result.get("resultUrls")
        if not isinstance(urls, list) or len(urls) != 1 or not KieVideoProviderAdapter._safe_https_uri(urls[0]):
            raise AdapterFailure(
                "KIE_RESPONSE_INVALID",
                "KIE result URL is invalid",
                retryable=False,
                http_status=200,
                provider_error_summary=self._provider_summary(result),
            )
        return str(urls[0])

    @staticmethod
    def _safe_https_uri(raw: object) -> bool:
        if not isinstance(raw, str) or contains_sensitive_text(raw):
            return False
        parsed = urlparse(raw)
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment)

    def _validated_task_id(self, raw: object) -> str:
        if (
            not isinstance(raw, str)
            or _TASK_ID.fullmatch(raw) is None
            or contains_sensitive_text(raw)
            or raw == self._credential_resolver.resolve()
        ):
            raise AdapterFailure("KIE_REQUEST_INVALID", "KIE task identity is invalid", retryable=False)
        return raw
