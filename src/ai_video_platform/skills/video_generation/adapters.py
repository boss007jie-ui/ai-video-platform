"""Offline-only Provider seams for deterministic generation tests."""

from __future__ import annotations

import hashlib
from typing import Mapping, Protocol


class VideoProviderAdapter(Protocol):
    def submit(self, request: Mapping[str, object]) -> str: ...
    def poll(self, provider_job_id: str) -> Mapping[str, object]: ...
    def cancel(self, provider_job_id: str) -> None: ...
    def download(self, provider_job_id: str) -> Mapping[str, object]: ...


class AdapterFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class FakeVideoProviderAdapter:
    """Deterministic in-memory fake; it never imports or touches networking."""

    execution_mode = "offline_adapter"
    network_performed = False

    def __init__(
        self,
        *,
        poll_states: tuple[str, ...] = ("succeeded",),
        submit_failures: int = 0,
        poll_failures: int = 0,
        corrupt_download: bool = False,
        artifact_content: bytes = b"synthetic-video",
        artifact_content_type: str = "video/mp4",
        artifact_uri: str | None = None,
    ) -> None:
        self._poll_states = poll_states
        self._remaining_submit_failures = submit_failures
        self._remaining_poll_failures = poll_failures
        self._corrupt_download = corrupt_download
        self._artifact_content = bytes(artifact_content)
        self._artifact_content_type = artifact_content_type
        self._artifact_uri = artifact_uri
        self._jobs: dict[str, dict[str, object]] = {}
        self.submit_count = 0
        self.network_calls = 0
        self.last_submission: dict[str, object] | None = None

    @property
    def job_count(self) -> int:
        return len(self._jobs)

    def submit(self, request: Mapping[str, object]) -> str:
        self.submit_count += 1
        self.last_submission = dict(request)
        if self._remaining_submit_failures:
            self._remaining_submit_failures -= 1
            raise AdapterFailure("TRANSIENT", "Synthetic transient submit failure", retryable=True)
        identity = str(request["request_hash"]) + ":" + str(request["idempotency_key"])
        provider_job_id = "fake-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        self._jobs.setdefault(provider_job_id, {"poll_index": 0, "cancelled": False})
        return provider_job_id

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        job = self._job(provider_job_id)
        if self._remaining_poll_failures:
            self._remaining_poll_failures -= 1
            raise AdapterFailure("TRANSIENT", "Synthetic transient poll failure", retryable=True)
        if job["cancelled"]:
            return {"state": "cancelled"}
        index = int(job["poll_index"])
        state = self._poll_states[min(index, len(self._poll_states) - 1)]
        job["poll_index"] = index + 1
        return {"state": state}

    def cancel(self, provider_job_id: str) -> None:
        self._job(provider_job_id)["cancelled"] = True

    def download(self, provider_job_id: str) -> Mapping[str, object]:
        self._job(provider_job_id)
        content = self._artifact_content
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if self._corrupt_download:
            digest = "sha256:" + "0" * 64
        return {
            "content": content,
            "sha256": digest,
            "uri": self._artifact_uri or "memory://" + provider_job_id + ".mp4",
            "content_type": self._artifact_content_type,
        }

    def _job(self, provider_job_id: str) -> dict[str, object]:
        try:
            return self._jobs[provider_job_id]
        except KeyError as exc:
            raise AdapterFailure("NOT_FOUND", "Synthetic Provider job is absent", retryable=False) from exc


class RejectingVideoProviderAdapter:
    execution_mode = "offline_adapter"
    network_performed = False
    network_calls = 0

    def submit(self, request: Mapping[str, object]) -> str:
        raise AdapterFailure("PROVIDER_REJECTED", "Provider execution is rejected by policy", retryable=False)

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        raise AdapterFailure("PROVIDER_REJECTED", "Provider execution is rejected by policy", retryable=False)

    def cancel(self, provider_job_id: str) -> None:
        raise AdapterFailure("PROVIDER_REJECTED", "Provider execution is rejected by policy", retryable=False)

    def download(self, provider_job_id: str) -> Mapping[str, object]:
        raise AdapterFailure("PROVIDER_REJECTED", "Provider execution is rejected by policy", retryable=False)


class NetworkBlockedVideoProviderAdapter:
    execution_mode = "offline_adapter"
    network_performed = False
    network_calls = 0

    def submit(self, request: Mapping[str, object]) -> str:
        raise AdapterFailure("NETWORK_BLOCKED", "Production Provider network path is not authorized", retryable=False)

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        raise AdapterFailure("NETWORK_BLOCKED", "Production Provider network path is not authorized", retryable=False)

    def cancel(self, provider_job_id: str) -> None:
        raise AdapterFailure("NETWORK_BLOCKED", "Production Provider network path is not authorized", retryable=False)

    def download(self, provider_job_id: str) -> Mapping[str, object]:
        raise AdapterFailure("NETWORK_BLOCKED", "Production Provider network path is not authorized", retryable=False)
