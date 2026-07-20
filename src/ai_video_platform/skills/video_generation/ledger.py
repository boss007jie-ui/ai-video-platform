"""Thread-safe in-memory execution ledger with snapshot-only public reads."""

from __future__ import annotations

from threading import Condition, RLock
from typing import Mapping

from .errors import GenerationError, GenerationErrorCode
from .models import snapshot


ACTIVE_STATES = {"submitting", "submitted", "polling", "recovery_required"}
ALLOWED_TRANSITIONS = {
    "submitting": {"submitted", "failed"},
    "submitted": {"polling", "succeeded", "failed", "cancelled", "timed_out", "recovery_required"},
    "polling": {"polling", "succeeded", "failed", "cancelled", "timed_out", "recovery_required"},
    "recovery_required": {"polling", "succeeded", "failed", "cancelled", "timed_out", "recovery_required"},
    "succeeded": {"downloaded"},
    "failed": set(), "cancelled": set(), "timed_out": set(), "downloaded": set(),
}


class InMemoryVideoExecutionLedger:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, object]] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = RLock()
        self._changed = Condition(self._lock)

    def reserve(
        self,
        record: Mapping[str, object],
        *,
        max_requests: int,
        max_concurrency: int,
    ) -> tuple[dict[str, object], bool]:
        """Atomically enforce both limits and reserve idempotency/job identity."""

        value = snapshot(record)
        value["history"] = [{"state": value["state"], "at": value["submitted_at"]}]
        job_id = str(value["job_id"])
        key = str(value["idempotency_key"])
        with self._lock:
            existing_job_id = self._idempotency.get(key)
            if existing_job_id is not None:
                existing = self._records[existing_job_id]
                if existing["request_hash"] != value["request_hash"]:
                    raise GenerationError(
                        GenerationErrorCode.IDEMPOTENCY_MISMATCH,
                        "Idempotency key was already used for a different request",
                    )
                return snapshot(existing), False
            if job_id in self._records:
                raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Execution identity already exists")
            request_limits = [max_requests, *(int(item["budget"]["max_requests"]) for item in self._records.values())]
            if len(self._records) >= min(request_limits):
                raise GenerationError(GenerationErrorCode.REQUEST_LIMIT, "Approved request limit is exhausted")
            active_records = [item for item in self._records.values() if item["state"] in ACTIVE_STATES]
            concurrency_limits = [max_concurrency, *(int(item["budget"]["max_concurrency"]) for item in active_records)]
            if len(active_records) >= min(concurrency_limits):
                raise GenerationError(GenerationErrorCode.CONCURRENCY_LIMIT, "Approved concurrency limit is exhausted")
            self._records[job_id] = value
            self._idempotency[key] = job_id
            return snapshot(value), True

    def get(self, job_id: str) -> dict[str, object]:
        with self._lock:
            try:
                return snapshot(self._records[job_id])
            except KeyError:
                raise GenerationError(GenerationErrorCode.JOB_NOT_FOUND, "Video execution job was not found") from None

    def active_count(self) -> int:
        with self._lock:
            return sum(record["state"] in ACTIVE_STATES for record in self._records.values())

    def recoverable(self) -> list[dict[str, object]]:
        with self._lock:
            return [snapshot(record) for record in self._records.values() if record["state"] in ACTIVE_STATES]

    def wait_for_submission(self, job_id: str, timeout_seconds: float) -> dict[str, object]:
        with self._changed:
            if job_id not in self._records:
                raise GenerationError(GenerationErrorCode.JOB_NOT_FOUND, "Video execution job was not found")
            completed = self._changed.wait_for(lambda: self._records[job_id]["state"] != "submitting", timeout=timeout_seconds)
            if not completed:
                raise GenerationError(GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED, "Concurrent submission did not complete in time", retryable=True)
            return snapshot(self._records[job_id])

    def transition(self, job_id: str, *, expected_states: set[str], state: str, at: str, **changes: object) -> dict[str, object]:
        safe_changes = snapshot(changes)
        with self._lock:
            if job_id not in self._records:
                raise GenerationError(GenerationErrorCode.JOB_NOT_FOUND, "Video execution job was not found")
            record = self._records[job_id]
            current = str(record["state"])
            if current not in expected_states or state not in ALLOWED_TRANSITIONS.get(current, set()):
                raise GenerationError(GenerationErrorCode.INVALID_TRANSITION, "Video execution state transition is invalid")
            record.update(safe_changes)
            record["state"] = state
            record["history"].append({"state": state, "at": at})
            self._changed.notify_all()
            return snapshot(record)
