"""Explicit KIE production adapter for the authorized Seedance smoke path."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .adapters import AdapterFailure
from .errors import contains_sensitive_text


KIE_MODEL_ID = "bytedance/seedance-2-mini"
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


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class UrllibKieHttpTransport:
    """Small stdlib HTTP transport; authentication is sent only to api.kie.ai."""

    _BASE_URL = "https://api.kie.ai"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds
        self._api_opener = build_opener(_NoRedirectHandler())

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
                raw = response.read()
        except HTTPError as error:
            retryable = error.code == 429 or error.code >= 500
            raise AdapterFailure("KIE_HTTP_ERROR", "KIE API rejected the request", retryable=retryable) from None
        except (URLError, TimeoutError, OSError):
            raise AdapterFailure("KIE_NETWORK_ERROR", "KIE API network request failed", retryable=True) from None
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE API returned malformed JSON", retryable=False) from None
        if not isinstance(decoded, dict):
            raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE API returned malformed JSON", retryable=False)
        return decoded

    def download(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise AdapterFailure("KIE_DOWNLOAD_INVALID", "KIE artifact URL is invalid", retryable=False)
        request = Request(uri, method="GET", headers={"Accept": "video/mp4,application/octet-stream"})
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                return response.read()
        except HTTPError as error:
            retryable = error.code == 429 or error.code >= 500
            raise AdapterFailure("KIE_DOWNLOAD_ERROR", "KIE artifact download failed", retryable=retryable) from None
        except (URLError, TimeoutError, OSError):
            raise AdapterFailure("KIE_DOWNLOAD_ERROR", "KIE artifact download failed", retryable=True) from None


class KieVideoProviderAdapter:
    """KIE adapter with FTG-P-VIDEO-001 limits enforced before network access."""

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

    def submit(self, request: Mapping[str, object]) -> str:
        payload = self._submission_payload(request)
        try:
            response = self._request_json("POST", "/api/v1/jobs/createTask", payload=payload)
        except AdapterFailure as error:
            raise AdapterFailure(
                error.code,
                "KIE submission failed with no safe automatic retry",
                retryable=False,
            ) from None
        data = self._success_data(response)
        task_id = data.get("taskId")
        if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None or contains_sensitive_text(task_id):
            raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE API returned an invalid task identity", retryable=False)
        return task_id

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        task_id = self._validated_task_id(provider_job_id)
        response = self._request_json(
            "GET",
            "/api/v1/jobs/recordInfo",
            query={"taskId": task_id},
        )
        data = self._success_data(response)
        if data.get("taskId") != task_id or data.get("model") not in {None, KIE_MODEL_ID}:
            raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE task response identity is invalid", retryable=False)
        state = data.get("state")
        mapped = {
            "waiting": "running",
            "queuing": "running",
            "generating": "running",
            "success": "succeeded",
            "fail": "failed",
        }.get(state)
        if mapped is None:
            raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE task state is unsupported", retryable=False)
        result: dict[str, object] = {"state": mapped}
        cost = data.get("creditsConsumed")
        if cost is not None:
            if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
                raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE task cost is invalid", retryable=False)
            result["cost_units"] = cost
        if mapped == "succeeded":
            result_uri = self._result_uri(data.get("resultJson"))
            self._completed[task_id] = {"result_uri": result_uri, **result}
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
        content = self._download(str(completed["result_uri"]))
        if not content:
            raise AdapterFailure("KIE_DOWNLOAD_INVALID", "KIE artifact is empty", retryable=False)
        import hashlib

        return {
            "content": content,
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "uri": f"kie://{task_id}/video.mp4",
            "content_type": "video/mp4",
        }

    def _submission_payload(self, request: Mapping[str, object]) -> dict[str, object]:
        binding = request.get("provider_binding")
        budget = request.get("budget")
        output = request.get("output")
        if not isinstance(binding, Mapping) or binding.get("provider_id") != "kie" or binding.get("model_id") != KIE_MODEL_ID:
            raise AdapterFailure("KIE_GUARDRAIL", "KIE provider binding is not authorized", retryable=False)
        if not isinstance(budget, Mapping) or any(
            budget.get(field) != expected
            for field, expected in (("max_requests", 1), ("max_concurrency", 1), ("max_attempts", 2), ("timeout_seconds", 600))
        ):
            raise AdapterFailure("KIE_GUARDRAIL", "KIE smoke budget guardrail is invalid", retryable=False)
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

    @staticmethod
    def _success_data(response: object) -> dict[str, object]:
        if not isinstance(response, Mapping) or response.get("code") != 200 or not isinstance(response.get("data"), Mapping):
            raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE API returned an unsuccessful response", retryable=False)
        return dict(response["data"])

    @staticmethod
    def _result_uri(raw: object) -> str:
        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE result metadata is malformed", retryable=False) from None
        if not isinstance(result, Mapping):
            raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE result metadata is malformed", retryable=False)
        urls = result.get("resultUrls")
        if not isinstance(urls, list) or len(urls) != 1 or not KieVideoProviderAdapter._safe_https_uri(urls[0]):
            raise AdapterFailure("KIE_RESPONSE_INVALID", "KIE result URL is invalid", retryable=False)
        return str(urls[0])

    @staticmethod
    def _safe_https_uri(raw: object) -> bool:
        if not isinstance(raw, str) or contains_sensitive_text(raw):
            return False
        parsed = urlparse(raw)
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment)

    @staticmethod
    def _validated_task_id(raw: object) -> str:
        if not isinstance(raw, str) or _TASK_ID.fullmatch(raw) is None or contains_sensitive_text(raw):
            raise AdapterFailure("KIE_REQUEST_INVALID", "KIE task identity is invalid", retryable=False)
        return raw
