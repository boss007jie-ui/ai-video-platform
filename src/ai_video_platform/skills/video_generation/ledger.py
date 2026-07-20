"""Thread-safe in-memory execution ledger with snapshot-only public reads."""

from __future__ import annotations

from threading import RLock
from typing import Mapping

from .errors import GenerationError, GenerationErrorCode
from .models import snapshot


ACTIVE_STATES = {"submitting", "submitted", "running"}


class InMemoryVideoExecutionLedger:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, object]] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = RLock()

    def idempotent(self, key: str, request_hash: str) -> dict[str, object] | None:
        with self._lock:
            job_id = self._idempotency.get(key)
            if job_id is None:
                return None
            record = self._records[job_id]
            if record["request_hash"] != request_hash:
                raise GenerationError(
                    GenerationErrorCode.IDEMPOTENCY_MISMATCH,
                    "Idempotency key was already used for a different request",
                )
            return snapshot(record)

    def enforce_limits(self, *, max_requests: int, max_concurrency: int) -> None:
        with self._lock:
            if len(self._records) >= max_requests:
                raise GenerationError(GenerationErrorCode.REQUEST_LIMIT, "Approved request limit is exhausted")
            active = sum(record["state"] in ACTIVE_STATES for record in self._records.values())
            if active >= max_concurrency:
                raise GenerationError(GenerationErrorCode.CONCURRENCY_LIMIT, "Approved concurrency limit is exhausted")

    def reserve(
        self,
        record: Mapping[str, object],
        *,
        max_requests: int,
        max_concurrency: int,
    ) -> dict[str, object]:
        """Atomically enforce both limits and reserve idempotency/job identity."""

        value = snapshot(record)
        job_id = str(value["job_id"])
        key = str(value["idempotency_key"])
        with self._lock:
            if key in self._idempotency or job_id in self._records:
                raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Execution identity already exists")
            if len(self._records) >= max_requests:
                raise GenerationError(GenerationErrorCode.REQUEST_LIMIT, "Approved request limit is exhausted")
            active = sum(item["state"] in ACTIVE_STATES for item in self._records.values())
            if active >= max_concurrency:
                raise GenerationError(GenerationErrorCode.CONCURRENCY_LIMIT, "Approved concurrency limit is exhausted")
            self._records[job_id] = value
            self._idempotency[key] = job_id
            return snapshot(value)

    def create(self, record: Mapping[str, object]) -> dict[str, object]:
        value = snapshot(record)
        job_id = str(value["job_id"])
        key = str(value["idempotency_key"])
        with self._lock:
            if job_id in self._records or key in self._idempotency:
                raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Execution identity already exists")
            self._records[job_id] = value
            self._idempotency[key] = job_id
            return snapshot(value)

    def get(self, job_id: str) -> dict[str, object]:
        with self._lock:
            try:
                return snapshot(self._records[job_id])
            except KeyError:
                raise GenerationError(GenerationErrorCode.JOB_NOT_FOUND, "Video execution job was not found") from None

    def update(self, job_id: str, **changes: object) -> dict[str, object]:
        safe_changes = snapshot(changes)
        with self._lock:
            if job_id not in self._records:
                raise GenerationError(GenerationErrorCode.JOB_NOT_FOUND, "Video execution job was not found")
            self._records[job_id].update(safe_changes)
            return snapshot(self._records[job_id])
