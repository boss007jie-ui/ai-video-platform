"""Independent thread-safe in-memory enhancement ledger."""

from __future__ import annotations

from threading import Condition, RLock
from typing import Mapping

from .errors import EnhancementError, EnhancementErrorCode
from .models import snapshot


ACTIVE_STATES = {"submitting", "submitted", "polling", "recovery_required"}
ALLOWED_TRANSITIONS = {
    "submitting": {"submitted", "failed", "recovery_required"},
    "submitted": {"polling", "succeeded", "failed", "cancelled", "timed_out", "recovery_required"},
    "polling": {"polling", "succeeded", "failed", "cancelled", "timed_out", "recovery_required"},
    "recovery_required": {"polling", "succeeded", "failed", "cancelled", "timed_out", "recovery_required"},
    "succeeded": {"downloaded", "failed"},
    "failed": set(),
    "cancelled": set(),
    "timed_out": set(),
    "downloaded": set(),
}


class InMemoryEnhancementLedger:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, object]] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = RLock()
        self._changed = Condition(self._lock)

    def reserve(self, record: Mapping[str, object], *, max_requests: int, max_concurrency: int) -> tuple[dict[str, object], bool]:
        value = snapshot(record)
        value["history"] = [{"state": value["state"], "at": value["submitted_at"]}]
        job_id = str(value["job_id"])
        key = str(value["idempotency_key"])
        with self._lock:
            existing_id = self._idempotency.get(key)
            if existing_id is not None:
                existing = self._records[existing_id]
                if existing["request_hash"] != value["request_hash"]:
                    raise EnhancementError(EnhancementErrorCode.IDEMPOTENCY_MISMATCH, "idempotency key is bound to a different request")
                return snapshot(existing), False
            request_limits = [max_requests, *(int(item["budget"]["max_requests"]) for item in self._records.values())]
            if len(self._records) >= min(request_limits):
                raise EnhancementError(EnhancementErrorCode.REQUEST_LIMIT, "enhancement request limit is exhausted")
            active = [item for item in self._records.values() if item["state"] in ACTIVE_STATES]
            concurrency_limits = [max_concurrency, *(int(item["budget"]["max_concurrency"]) for item in active)]
            if len(active) >= min(concurrency_limits):
                raise EnhancementError(EnhancementErrorCode.CONCURRENCY_LIMIT, "enhancement concurrency limit is exhausted")
            self._records[job_id] = value
            self._idempotency[key] = job_id
            return snapshot(value), True

    def get(self, job_id: str) -> dict[str, object]:
        with self._lock:
            try:
                return snapshot(self._records[job_id])
            except KeyError:
                raise EnhancementError(EnhancementErrorCode.JOB_NOT_FOUND, "enhancement job was not found") from None

    def active_count(self) -> int:
        with self._lock:
            return sum(item["state"] in ACTIVE_STATES for item in self._records.values())

    def recoverable(self) -> list[dict[str, object]]:
        with self._lock:
            return [snapshot(item) for item in self._records.values() if item["state"] in ACTIVE_STATES]

    def wait_for_submission(self, job_id: str, timeout_seconds: float) -> dict[str, object]:
        with self._changed:
            if job_id not in self._records:
                raise EnhancementError(EnhancementErrorCode.JOB_NOT_FOUND, "enhancement job was not found")
            completed = self._changed.wait_for(lambda: self._records[job_id]["state"] != "submitting", timeout=timeout_seconds)
            if not completed:
                raise EnhancementError(EnhancementErrorCode.PROVIDER_RETRY_EXHAUSTED, "concurrent enhancement submission did not finish", retryable=True)
            return snapshot(self._records[job_id])

    def transition(self, job_id: str, *, expected_states: set[str], state: str, at: str, **changes: object) -> dict[str, object]:
        safe_changes = snapshot(changes)
        with self._changed:
            if job_id not in self._records:
                raise EnhancementError(EnhancementErrorCode.JOB_NOT_FOUND, "enhancement job was not found")
            record = self._records[job_id]
            current = str(record["state"])
            if current not in expected_states or state not in ALLOWED_TRANSITIONS.get(current, set()):
                raise EnhancementError(EnhancementErrorCode.INVALID_TRANSITION, "enhancement state transition is invalid")
            record.update(safe_changes)
            record["state"] = state
            record["history"].append({"state": state, "at": at})
            self._changed.notify_all()
            return snapshot(record)
