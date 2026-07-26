"""Offline-only adapter seam for Video Enhancement."""

from __future__ import annotations

import hashlib
from typing import Mapping, Protocol


class VideoEnhancementAdapter(Protocol):
    """Provider-neutral adapter seam used by the orchestration interface."""

    def submit(self, request: Mapping[str, object]) -> str: ...
    def poll(self, provider_job_id: str) -> Mapping[str, object]: ...
    def cancel(self, provider_job_id: str) -> None: ...
    def download(self, provider_job_id: str) -> Mapping[str, object]: ...


class AdapterFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class FakeVideoEnhancementAdapter:
    execution_mode = "offline_adapter"
    network_performed = False

    def __init__(
        self,
        *,
        poll_states: tuple[str, ...] = ("succeeded",),
        submit_failures: int = 0,
        poll_failures: int = 0,
        artifact_content: bytes = b"synthetic-enhanced-video",
        corrupt_download: bool = False,
    ) -> None:
        self._poll_states = poll_states
        self._submit_failures = submit_failures
        self._poll_failures = poll_failures
        self._artifact_content = bytes(artifact_content)
        self._corrupt_download = corrupt_download
        self._jobs: dict[str, dict[str, object]] = {}
        self.network_calls = 0
        self.submit_count = 0
        self.last_provider_job_id = ""

    def submit(self, request: Mapping[str, object]) -> str:
        self.submit_count += 1
        if self._submit_failures:
            self._submit_failures -= 1
            raise AdapterFailure("TRANSIENT", "Synthetic submit failure", retryable=True)
        basis = str(request["request_hash"]) + ":" + str(request["idempotency_key"])
        provider_job_id = "fake-enh-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]
        self._jobs.setdefault(provider_job_id, {"poll_index": 0, "cancelled": False})
        self.last_provider_job_id = provider_job_id
        return provider_job_id

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        job = self._job(provider_job_id)
        if self._poll_failures:
            self._poll_failures -= 1
            raise AdapterFailure("TRANSIENT", "Synthetic poll failure", retryable=True)
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
        digest = "sha256:" + hashlib.sha256(self._artifact_content).hexdigest()
        if self._corrupt_download:
            digest = "sha256:" + "0" * 64
        return {
            "content": self._artifact_content,
            "sha256": digest,
            "media_type": "video/mp4",
            "source_uri": "memory://" + provider_job_id + "/enhanced.mp4",
        }

    def _job(self, provider_job_id: str) -> dict[str, object]:
        try:
            return self._jobs[provider_job_id]
        except KeyError:
            raise AdapterFailure("NOT_FOUND", "Synthetic enhancement job is absent", retryable=False) from None


class RejectingVideoEnhancementAdapter:
    execution_mode = "offline_adapter"
    network_performed = False
    network_calls = 0

    @staticmethod
    def _reject() -> None:
        raise AdapterFailure("PROVIDER_REJECTED", "Enhancement Provider execution is rejected by policy", retryable=False)

    def submit(self, request: Mapping[str, object]) -> str:
        del request
        self._reject()
        raise AssertionError("unreachable")

    def poll(self, provider_job_id: str) -> Mapping[str, object]:
        del provider_job_id
        self._reject()
        raise AssertionError("unreachable")

    def cancel(self, provider_job_id: str) -> None:
        del provider_job_id
        self._reject()

    def download(self, provider_job_id: str) -> Mapping[str, object]:
        del provider_job_id
        self._reject()
        raise AssertionError("unreachable")
