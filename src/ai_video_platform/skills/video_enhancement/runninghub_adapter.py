"""RunningHub production adapter and deterministic offline test double."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
from time import monotonic, sleep as system_sleep
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .adapters import AdapterFailure
from .errors import contains_sensitive_text


BASE_URL = "https://www.runninghub.ai"
MAX_INPUT_BYTES = 30 * 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 512 * 1024 * 1024
POLL_INTERVAL_SECONDS = 5.0
MAX_POLLS = 120
TIMEOUT_SECONDS = 600.0
_ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
_CREDENTIAL = re.compile(r"^[A-Za-z0-9._~-]{12,256}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RUNNING = {"RUNNING", "QUEUED", "PENDING", "SUBMITTED"}
_FAILED = {"FAILED", "FAILURE", "ERROR"}
_SUCCEEDED = {"SUCCESS", "SUCCEEDED", "COMPLETED"}


def _matches_container(extension: str, content: bytes) -> bool:
    if extension in {".mp4", ".mov"}:
        return len(content) >= 12 and content[4:8] == b"ftyp"
    if extension == ".avi":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"AVI "
    return extension == ".mkv" and content.startswith(b"\x1aE\xdf\xa3")


def _is_mp4(content: bytes) -> bool:
    return len(content) >= 12 and content[4:8] == b"ftyp"


def _safe_https_url(value: object) -> bool:
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


def _origin(value: str) -> str:
    parsed = urlparse(value)
    return f"{parsed.scheme}://{parsed.netloc}"


class RunningHubCredentialResolver:
    """Resolve the one authorized environment reference at execution time."""

    def __init__(self, *, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    def resolve(self) -> str:
        value = self._environ.get("RUNNINGHUB_API_KEY")
        if not isinstance(value, str) or _CREDENTIAL.fullmatch(value) is None:
            raise AdapterFailure(
                "CREDENTIAL_UNAVAILABLE",
                "RunningHub credential environment reference is unavailable",
                retryable=False,
            )
        return value


class _RunningHubTransport(Protocol):
    def upload_multipart(
        self,
        credential: str,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
    ) -> object: ...

    def request_json(
        self,
        method: str,
        path: str,
        credential: str,
        *,
        payload: dict[str, object],
    ) -> object: ...

    def download(self, uri: str, *, max_bytes: int) -> tuple[bytes, str]: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class _UrllibRunningHubTransport:
    """Stdlib HTTP transport with fixed API origin and redirects disabled."""

    def __init__(self, *, timeout_seconds: float = 30.0, opener: object | None = None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener or build_opener(_NoRedirectHandler())
        self.network_calls = 0

    def upload_multipart(
        self,
        credential: str,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
    ) -> object:
        boundary = "runninghub-" + hashlib.sha256(file_name.encode("utf-8") + b"\0" + file_bytes).hexdigest()[:24]
        body = b"".join((
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8"),
            f"Content-Type: {media_type}\r\n\r\n".encode("ascii"),
            file_bytes,
            f"\r\n--{boundary}--\r\n".encode("ascii"),
        ))
        request = Request(
            BASE_URL + "/task/openapi/upload",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer " + credential,
                "Accept": "application/json",
                "Content-Type": "multipart/form-data; boundary=" + boundary,
            },
        )
        raw, _ = self._open(request, max_bytes=1024 * 1024)
        return self._decode_json(raw)

    def request_json(
        self,
        method: str,
        path: str,
        credential: str,
        *,
        payload: dict[str, object],
    ) -> object:
        if method != "POST" or path not in {"/task/openapi/create", "/task/openapi/outputs"}:
            raise AdapterFailure("REQUEST_INVALID", "RunningHub request target is invalid", retryable=False)
        request = Request(
            BASE_URL + path,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": "Bearer " + credential,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        raw, _ = self._open(request, max_bytes=1024 * 1024)
        return self._decode_json(raw)

    def download(self, uri: str, *, max_bytes: int) -> tuple[bytes, str]:
        if not _safe_https_url(uri):
            raise AdapterFailure("DOWNLOAD_INVALID", "RunningHub output URL is invalid", retryable=False)
        request = Request(uri, method="GET", headers={"Accept": "video/*"})
        return self._open(request, max_bytes=max_bytes)

    def _open(self, request: Request, *, max_bytes: int) -> tuple[bytes, str]:
        try:
            self.network_calls += 1
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get_content_type())
                content_length = response.headers.get("Content-Length")
                if isinstance(content_length, str) and content_length.isdigit() and int(content_length) > max_bytes:
                    raise AdapterFailure("RESPONSE_TOO_LARGE", "RunningHub response exceeds the byte limit", retryable=False)
                raw = response.read(max_bytes + 1)
        except HTTPError as error:
            error.close()
            raise AdapterFailure("HTTP_ERROR", "RunningHub API rejected the request", retryable=False) from None
        except (URLError, TimeoutError, OSError):
            raise AdapterFailure("NETWORK_ERROR", "RunningHub network request failed", retryable=False) from None
        if status != 200:
            raise AdapterFailure("HTTP_ERROR", "RunningHub API rejected the request", retryable=False)
        if len(raw) > max_bytes:
            raise AdapterFailure("RESPONSE_TOO_LARGE", "RunningHub response exceeds the byte limit", retryable=False)
        return raw, content_type

    @staticmethod
    def _decode_json(raw: bytes) -> object:
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AdapterFailure("RESPONSE_INVALID", "RunningHub returned malformed JSON", retryable=False) from None


class RunningHubVideoEnhancementAdapter:
    """Production adapter available only through explicit owner CLI selection."""

    execution_mode = "runninghub_production"
    network_performed = True

    def __init__(
        self,
        *,
        transport: _RunningHubTransport | None = None,
        credential_resolver: RunningHubCredentialResolver | None = None,
        clock: Callable[[], float] = monotonic,
        sleep: Callable[[float], None] = system_sleep,
        poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
        max_polls: int = MAX_POLLS,
        timeout_seconds: float = TIMEOUT_SECONDS,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        if poll_interval_seconds < POLL_INTERVAL_SECONDS:
            raise ValueError("poll_interval_seconds must be at least 5 seconds")
        if isinstance(max_polls, bool) or not isinstance(max_polls, int) or not 1 <= max_polls <= MAX_POLLS:
            raise ValueError("max_polls must be within the authorized 120 poll limit")
        if timeout_seconds <= 0 or timeout_seconds > TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be within the authorized 600 second limit")
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self._transport = transport or _UrllibRunningHubTransport()
        self._credential_resolver = credential_resolver or RunningHubCredentialResolver()
        self._clock = clock
        self._sleep = sleep
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._max_polls = max_polls
        self._timeout_seconds = float(timeout_seconds)
        self._max_output_bytes = max_output_bytes
        self._jobs: dict[str, dict[str, object]] = {}
        self.network_calls = 0

    @property
    def status_chain(self) -> tuple[str, ...]:
        if len(self._jobs) != 1:
            return ()
        return tuple(str(item) for item in next(iter(self._jobs.values()))["status_chain"])

    def submit(self, request: Mapping[str, object]) -> str:
        file_name, file_bytes, media_type = self._input_file(request)
        (
            workflow_id,
            node_info_list,
            output_origins,
            workflow_digest,
            input_node_id,
            input_field_name,
        ) = self._workflow_binding(request)
        credential = self._credential_resolver.resolve()
        upload = self._call(
            "UPLOAD_FAILED",
            lambda: self._transport.upload_multipart(
                credential,
                file_name=file_name,
                file_bytes=file_bytes,
                media_type=media_type,
            ),
        )
        uploaded_name = self._uploaded_file_name(upload)
        populated_nodes = self._populate_input_node(
            node_info_list,
            uploaded_name,
            input_node_id=input_node_id,
            input_field_name=input_field_name,
        )
        payload: dict[str, object] = {"workflowId": workflow_id, "nodeInfoList": populated_nodes}
        created = self._call(
            "CREATE_FAILED",
            lambda: self._transport.request_json(
                "POST",
                "/task/openapi/create",
                credential,
                payload=payload,
            ),
        )
        task_id = self._task_id(created)
        if task_id in self._jobs:
            raise AdapterFailure("RESPONSE_INVALID", "RunningHub returned a duplicate task identity", retryable=False)
        self._jobs[task_id] = {
            "credential": credential,
            "started_at": self._clock(),
            "last_poll_at": None,
            "poll_count": 0,
            "state": "submitted",
            "result_url": None,
            "task_cost_time": None,
            "downloaded": False,
            "output_origins": output_origins,
            "workflow_id": workflow_id,
            "workflow_json_sha256": workflow_digest,
            "status_chain": ["SUBMITTED"],
        }
        return task_id

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        job = self._job(provider_job_id)
        if job["state"] in {"succeeded", "failed"}:
            raise AdapterFailure("INVALID_TRANSITION", "RunningHub task is already terminal", retryable=False)
        now = self._clock()
        if now - float(job["started_at"]) > self._timeout_seconds:
            raise AdapterFailure("TIMEOUT", "RunningHub task exceeded 600 seconds", retryable=False)
        if int(job["poll_count"]) >= self._max_polls:
            raise AdapterFailure("POLL_LIMIT_EXCEEDED", "RunningHub task exceeded 120 polls", retryable=False)
        last_poll_at = job["last_poll_at"]
        if isinstance(last_poll_at, (int, float)):
            remaining = self._poll_interval_seconds - (now - float(last_poll_at))
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        if now - float(job["started_at"]) > self._timeout_seconds:
            raise AdapterFailure("TIMEOUT", "RunningHub task exceeded 600 seconds", retryable=False)
        response = self._call(
            "POLL_FAILED",
            lambda: self._transport.request_json(
                "POST",
                "/task/openapi/outputs",
                str(job["credential"]),
                payload={"taskId": provider_job_id},
            ),
        )
        job["last_poll_at"] = now
        job["poll_count"] = int(job["poll_count"]) + 1
        return self._normalize_poll(response, job)

    def cancel(self, provider_job_id: str) -> None:
        self._job(provider_job_id)
        raise AdapterFailure(
            "CANCEL_NOT_SUPPORTED",
            "RunningHub cancellation is outside the authorized endpoint set",
            retryable=False,
        )

    def download(self, provider_job_id: str) -> Mapping[str, object]:
        job = self._job(provider_job_id)
        if job["state"] != "succeeded" or not isinstance(job["result_url"], str):
            raise AdapterFailure("DOWNLOAD_NOT_READY", "RunningHub artifact is not completed", retryable=False)
        if job["downloaded"] is True:
            raise AdapterFailure("DOWNLOAD_LIMIT_EXCEEDED", "RunningHub artifact was already downloaded", retryable=False)
        result = self._call(
            "DOWNLOAD_FAILED",
            lambda: self._transport.download(str(job["result_url"]), max_bytes=self._max_output_bytes),
        )
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[0], bytes)
            or not isinstance(result[1], str)
        ):
            raise AdapterFailure("DOWNLOAD_INVALID", "RunningHub download response is invalid", retryable=False)
        content, media_type = result
        if (
            not content
            or len(content) > self._max_output_bytes
            or not media_type.lower().startswith("video/")
            or not _is_mp4(content)
        ):
            raise AdapterFailure("DOWNLOAD_INVALID", "RunningHub output is not an approved MP4", retryable=False)
        job["downloaded"] = True
        job["state"] = "downloaded"
        job["status_chain"].append("DOWNLOADED")
        return {
            "content": content,
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "media_type": media_type.split(";", 1)[0].strip().lower(),
            "source_uri": str(job["result_url"]),
            "task_cost_time": job["task_cost_time"],
        }

    def execution_summary(self, provider_job_id: str) -> dict[str, object]:
        job = self._job(provider_job_id)
        return {
            "task_id": provider_job_id,
            "task_cost_time": job["task_cost_time"],
            "status_chain": list(job["status_chain"]),
            "workflow_id": job["workflow_id"],
            "workflow_json_sha256": job["workflow_json_sha256"],
            "poll_calls": job["poll_count"],
        }

    def _normalize_poll(self, response: object, job: dict[str, object]) -> Mapping[str, object]:
        if not isinstance(response, Mapping):
            raise AdapterFailure("RESPONSE_INVALID", "RunningHub poll response is invalid", retryable=False)
        data = response.get("data")
        raw_status = response.get("status")
        if isinstance(data, Mapping):
            raw_status = data.get("status", raw_status)
        if raw_status is not None and not isinstance(raw_status, str):
            raise AdapterFailure("RESPONSE_INVALID", "RunningHub status is invalid", retryable=False)
        status = raw_status.upper() if isinstance(raw_status, str) else None
        outputs: object = data if isinstance(data, list) else None
        if isinstance(data, Mapping):
            outputs = data.get("outputs")
        if outputs is None:
            outputs = response.get("outputs")
        if status in _FAILED:
            job["state"] = "failed"
            job["status_chain"].append("FAILED")
            return {"state": "failed", "status": status}
        if status in _RUNNING:
            job["state"] = "running"
            job["status_chain"].append("RUNNING")
            return {"state": "running", "status": status}
        if status in _SUCCEEDED:
            result = self._completed_output(outputs, job)
            job["state"] = "succeeded"
            job["status_chain"].append("SUCCEEDED")
            return result
        if status is not None:
            raise AdapterFailure("RESPONSE_INVALID", "RunningHub status is unsupported", retryable=False)
        if isinstance(outputs, list):
            result = self._completed_output(outputs, job)
            job["state"] = "succeeded"
            job["status_chain"].append("SUCCEEDED")
            return result
        if isinstance(data, Mapping) and any(key in data for key in ("wssUrl", "wss_url", "clientId", "client_id")):
            job["state"] = "running"
            job["status_chain"].append("RUNNING")
            return {"state": "running", "status": "RUNNING"}
        raise AdapterFailure("RESPONSE_INVALID", "RunningHub poll response is invalid", retryable=False)

    def _completed_output(self, outputs: object, job: dict[str, object]) -> Mapping[str, object]:
        if not isinstance(outputs, list) or len(outputs) != 1 or not isinstance(outputs[0], Mapping):
            raise AdapterFailure("RESPONSE_INVALID", "RunningHub output list is invalid", retryable=False)
        output = outputs[0]
        result_url = output.get("fileUrl")
        file_type = output.get("fileType")
        task_cost_time = output.get("taskCostTime")
        if (
            not _safe_https_url(result_url)
            or _origin(str(result_url)) not in job["output_origins"]
            or not isinstance(file_type, str)
            or file_type.lower().lstrip(".") not in {"mp4", "video/mp4"}
            or isinstance(task_cost_time, bool)
            or not isinstance(task_cost_time, (int, float))
            or task_cost_time < 0
        ):
            raise AdapterFailure("RESPONSE_INVALID", "RunningHub completed output is invalid", retryable=False)
        job["result_url"] = result_url
        job["task_cost_time"] = task_cost_time
        return {"state": "succeeded", "status": "SUCCEEDED", "task_cost_time": task_cost_time}

    @staticmethod
    def _input_file(request: Mapping[str, object]) -> tuple[str, bytes, str]:
        raw = request.get("input")
        if not isinstance(raw, Mapping):
            raise AdapterFailure("INPUT_FILE_INVALID", "RunningHub input is invalid", retryable=False)
        path_value = raw.get("path")
        file_name = raw.get("file_name")
        if (
            not isinstance(path_value, str)
            or not isinstance(file_name, str)
            or any(marker in file_name for marker in ('"', "\r", "\n", "/", "\\"))
        ):
            raise AdapterFailure("INPUT_FILE_INVALID", "RunningHub input is invalid", retryable=False)
        path = Path(path_value)
        extension = path.suffix.lower()
        if path.name != file_name or path.is_symlink() or not path.is_file() or extension not in _ALLOWED_EXTENSIONS:
            raise AdapterFailure("INPUT_FILE_INVALID", "RunningHub input must be an approved local video", retryable=False)
        try:
            stat_before = path.stat()
            if stat_before.st_size > MAX_INPUT_BYTES:
                raise AdapterFailure("INPUT_TOO_LARGE", "RunningHub input exceeds 30MB", retryable=False)
            content = path.read_bytes()
            stat_after = path.stat()
        except OSError:
            raise AdapterFailure("INPUT_FILE_INVALID", "RunningHub input is unreadable", retryable=False) from None
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if (
            not content
            or len(content) > MAX_INPUT_BYTES
            or stat_before.st_size != stat_after.st_size
            or stat_before.st_mtime_ns != stat_after.st_mtime_ns
            or raw.get("size_bytes") != len(content)
            or raw.get("sha256") != digest
            or not _matches_container(extension, content)
        ):
            raise AdapterFailure("INPUT_FILE_INVALID", "RunningHub input verification failed", retryable=False)
        media_type = {
            ".mp4": "video/mp4",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
        }[extension]
        return file_name, content, media_type

    @staticmethod
    def _workflow_binding(
        request: Mapping[str, object],
    ) -> tuple[str, list[dict[str, object]], tuple[str, ...], str, str, str]:
        profile = request.get("workflow_profile")
        binding = profile.get("workflow_binding") if isinstance(profile, Mapping) else None
        required = {
            "workflow_id",
            "workflow_json_sha256",
            "input_node_id",
            "input_field_name",
            "node_info_list",
            "output_origins",
        }
        if not isinstance(binding, Mapping) or set(binding) != required:
            raise AdapterFailure("WORKFLOW_PROFILE_INVALID", "RunningHub workflow profile is not fixed", retryable=False)
        workflow_id = binding.get("workflow_id")
        workflow_digest = binding.get("workflow_json_sha256")
        input_node_id = binding.get("input_node_id")
        input_field_name = binding.get("input_field_name")
        node_info_list = binding.get("node_info_list")
        origins = binding.get("output_origins")
        if (
            not isinstance(workflow_id, str)
            or _IDENTITY.fullmatch(workflow_id) is None
            or not isinstance(workflow_digest, str)
            or _DIGEST.fullmatch(workflow_digest) is None
            or not isinstance(input_node_id, str)
            or _IDENTITY.fullmatch(input_node_id) is None
            or not isinstance(input_field_name, str)
            or _IDENTITY.fullmatch(input_field_name) is None
            or not isinstance(node_info_list, list)
            or not 1 <= len(node_info_list) <= 64
            or not isinstance(origins, list)
            or not origins
        ):
            raise AdapterFailure("WORKFLOW_PROFILE_INVALID", "RunningHub workflow profile is not fixed", retryable=False)
        normalized_nodes: list[dict[str, object]] = []
        input_matches = 0
        for item in node_info_list:
            if not isinstance(item, Mapping) or set(item) != {"nodeId", "fieldName", "fieldValue"}:
                raise AdapterFailure("WORKFLOW_PROFILE_INVALID", "RunningHub node binding is invalid", retryable=False)
            node_id = item.get("nodeId")
            field_name = item.get("fieldName")
            field_value = item.get("fieldValue")
            if (
                not isinstance(node_id, str)
                or _IDENTITY.fullmatch(node_id) is None
                or not isinstance(field_name, str)
                or _IDENTITY.fullmatch(field_name) is None
                or not isinstance(field_value, (str, int, float, bool))
                or (isinstance(field_value, str) and contains_sensitive_text(field_value))
            ):
                raise AdapterFailure("WORKFLOW_PROFILE_INVALID", "RunningHub node binding is invalid", retryable=False)
            if node_id == input_node_id and field_name == input_field_name:
                input_matches += 1
            normalized_nodes.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": field_value})
        normalized_origins: list[str] = []
        for item in origins:
            if not isinstance(item, str) or not _safe_https_url(item) or item != _origin(item):
                raise AdapterFailure("WORKFLOW_PROFILE_INVALID", "RunningHub output origin is invalid", retryable=False)
            normalized_origins.append(item)
        if input_matches != 1 or len(set(normalized_origins)) != len(normalized_origins):
            raise AdapterFailure("WORKFLOW_PROFILE_INVALID", "RunningHub workflow binding is ambiguous", retryable=False)
        return (
            workflow_id,
            normalized_nodes,
            tuple(normalized_origins),
            workflow_digest,
            input_node_id,
            input_field_name,
        )

    @staticmethod
    def _uploaded_file_name(response: object) -> str:
        data = response.get("data") if isinstance(response, Mapping) else None
        value = data.get("fileName") if isinstance(data, Mapping) else None
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 512
            or contains_sensitive_text(value)
            or value.startswith(("/", "\\"))
            or ".." in value.replace("\\", "/").split("/")
            or _safe_https_url(value)
        ):
            raise AdapterFailure("UPLOAD_RESPONSE_INVALID", "RunningHub upload file name is invalid", retryable=False)
        return value

    @staticmethod
    def _populate_input_node(
        node_info_list: list[dict[str, object]],
        file_name: str,
        *,
        input_node_id: str,
        input_field_name: str,
    ) -> list[dict[str, object]]:
        populated: list[dict[str, object]] = []
        replaced = False
        for item in node_info_list:
            value = dict(item)
            if value["nodeId"] == input_node_id and value["fieldName"] == input_field_name:
                if value["fieldValue"] != "UPLOAD_PLACEHOLDER":
                    raise AdapterFailure(
                        "WORKFLOW_PROFILE_INVALID",
                        "RunningHub input placeholder is invalid",
                        retryable=False,
                    )
                value["fieldValue"] = file_name
                replaced = True
            populated.append(value)
        if not replaced:
            raise AdapterFailure("WORKFLOW_PROFILE_INVALID", "RunningHub input placeholder is absent", retryable=False)
        return populated

    @staticmethod
    def _task_id(response: object) -> str:
        data = response.get("data") if isinstance(response, Mapping) else None
        value = data.get("taskId") if isinstance(data, Mapping) else None
        if value is None and isinstance(response, Mapping):
            value = response.get("taskId")
        if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None or contains_sensitive_text(value):
            raise AdapterFailure("CREATE_RESPONSE_INVALID", "RunningHub task identity is invalid", retryable=False)
        return value

    def _job(self, provider_job_id: str) -> dict[str, object]:
        try:
            return self._jobs[provider_job_id]
        except KeyError:
            raise AdapterFailure("NOT_FOUND", "RunningHub task is absent", retryable=False) from None

    def _call(self, fallback_code: str, operation: Callable[[], object]) -> object:
        try:
            self.network_calls += 1
            return operation()
        except AdapterFailure:
            raise
        except Exception:
            raise AdapterFailure(fallback_code, "RunningHub operation failed unexpectedly", retryable=False) from None


class FakeRunningHubVideoEnhancementAdapter:
    """Deterministic RunningHub-shaped adapter with no network seam."""

    execution_mode = "offline_adapter"
    network_performed = False
    network_calls = 0

    def __init__(
        self,
        *,
        artifact_content: bytes = b"\x00\x00\x00\x18ftypmp42synthetic-runninghub",
    ) -> None:
        self._artifact_content = bytes(artifact_content)
        self._jobs: dict[str, dict[str, object]] = {}

    def submit(self, request: Mapping[str, object]) -> str:
        identity = str(request.get("request_hash", "")) + ":" + str(request.get("idempotency_key", ""))
        task_id = "fake-rh-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        profile = request.get("workflow_profile")
        binding = profile.get("workflow_binding") if isinstance(profile, Mapping) else {}
        self._jobs.setdefault(task_id, {
            "state": "submitted",
            "workflow_id": binding.get("workflow_id") if isinstance(binding, Mapping) else None,
            "workflow_json_sha256": binding.get("workflow_json_sha256") if isinstance(binding, Mapping) else None,
            "status_chain": ["SUBMITTED"],
        })
        return task_id

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        if provider_job_id not in self._jobs:
            raise AdapterFailure("NOT_FOUND", "Synthetic RunningHub task is absent", retryable=False)
        self._jobs[provider_job_id]["state"] = "succeeded"
        self._jobs[provider_job_id]["status_chain"].append("SUCCEEDED")
        return {"state": "succeeded", "status": "SUCCEEDED", "task_cost_time": 0}

    def cancel(self, provider_job_id: str) -> None:
        if provider_job_id not in self._jobs:
            raise AdapterFailure("NOT_FOUND", "Synthetic RunningHub task is absent", retryable=False)
        self._jobs[provider_job_id]["state"] = "cancelled"
        self._jobs[provider_job_id]["status_chain"].append("CANCELLED")

    def download(self, provider_job_id: str) -> Mapping[str, object]:
        if provider_job_id not in self._jobs or self._jobs[provider_job_id]["state"] != "succeeded":
            raise AdapterFailure("DOWNLOAD_NOT_READY", "Synthetic RunningHub artifact is not ready", retryable=False)
        content = self._artifact_content
        self._jobs[provider_job_id]["state"] = "downloaded"
        self._jobs[provider_job_id]["status_chain"].append("DOWNLOADED")
        return {
            "content": content,
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "media_type": "video/mp4",
            "source_uri": "memory://runninghub/" + provider_job_id + "/enhanced.mp4",
            "task_cost_time": 0,
        }

    def execution_summary(self, provider_job_id: str) -> dict[str, object]:
        if provider_job_id not in self._jobs:
            raise AdapterFailure("NOT_FOUND", "Synthetic RunningHub task is absent", retryable=False)
        job = self._jobs[provider_job_id]
        return {
            "task_id": provider_job_id,
            "task_cost_time": 0,
            "status_chain": list(job["status_chain"]),
            "workflow_id": job["workflow_id"],
            "workflow_json_sha256": job["workflow_json_sha256"],
            "poll_calls": 1,
        }
