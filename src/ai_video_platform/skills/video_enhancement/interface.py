"""Public offline Video Enhancement interface and receipt orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib

from .adapters import AdapterFailure, FakeVideoEnhancementAdapter, RejectingVideoEnhancementAdapter, VideoEnhancementAdapter
from .errors import EnhancementError, EnhancementErrorCode, contains_sensitive_text, sanitize_sensitive
from .ledger import ACTIVE_STATES, InMemoryEnhancementLedger
from .models import CONTRACT_STATUS, SCHEMA_VERSION, content_digest, snapshot
from .preflight import EnhancementPreflight


class VideoEnhancementInterface:
    def __init__(
        self,
        *,
        adapter: VideoEnhancementAdapter | None = None,
        ledger: InMemoryEnhancementLedger | None = None,
    ) -> None:
        self._adapter = adapter
        self._ledger = ledger
        self._preflight = EnhancementPreflight()

    def inspect_enhancement_request(self, request: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
        return self._preflight.inspect(request, now=now)

    def submit_enhancement(self, request: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
        adapter, ledger = self._dependencies()
        evaluated_at = self._now(now)
        inspected = self._preflight.inspect(request, now=evaluated_at)
        budget = inspected["budget"]
        job_id = "enh-" + content_digest({
            "request_hash": inspected["request_hash"],
            "idempotency_key": inspected["idempotency_key"],
        }).removeprefix("sha256:")[:20]
        reserved, created = ledger.reserve({
            "job_id": job_id,
            "provider_job_id": "",
            "request_hash": inspected["request_hash"],
            "idempotency_key": inspected["idempotency_key"],
            "authorization": inspected["authorization"],
            "input_summary": inspected["input_summary"],
            "workflow_profile": inspected["workflow_profile"],
            "operations": inspected["operations"],
            "budget": budget,
            "cost_estimate": inspected["cost_estimate"],
            "state": "submitting",
            "attempts": 0,
            "submitted_at": self._format_time(evaluated_at),
        }, max_requests=int(budget["max_requests"]), max_concurrency=int(budget["max_concurrency"]))
        if not created:
            if reserved["state"] == "submitting":
                reserved = ledger.wait_for_submission(job_id, min(float(budget["timeout_seconds"]), 30.0))
            if reserved.get("state") in {"failed", "recovery_required", "timed_out", "cancelled"}:
                try:
                    code = EnhancementErrorCode(str(reserved.get("error_code")))
                except ValueError:
                    code = EnhancementErrorCode.INVALID_TRANSITION
                raise EnhancementError(
                    code,
                    "previously recorded enhancement execution failed",
                    details={"receipt": self._receipt(reserved)},
                    retryable=bool(reserved.get("retryable")),
                )
            return self._result(reserved, replayed=True)
        attempts = 0
        provider_job_id = ""
        while attempts < int(budget["max_attempts"]):
            attempts += 1
            try:
                candidate = adapter.submit(inspected)
                if not isinstance(candidate, str) or not candidate.strip() or contains_sensitive_text(candidate):
                    raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "adapter returned an invalid job identity")
                provider_job_id = candidate
                break
            except AdapterFailure as error:
                if not error.retryable:
                    updated = ledger.transition(job_id, expected_states={"submitting"}, state="failed", at=self._format_time(evaluated_at), attempts=attempts, error_code=self._adapter_code(error).value, retryable=False, error_summary=self._safe_error_summary(error))
                    raise EnhancementError(
                        self._adapter_code(error),
                        str(error),
                        details={"receipt": self._receipt(updated)},
                        retryable=False,
                    ) from None
            except EnhancementError as error:
                updated = ledger.transition(job_id, expected_states={"submitting"}, state="recovery_required", at=self._format_time(evaluated_at), attempts=attempts, error_code=EnhancementErrorCode.PROVIDER_REJECTED.value, retryable=False, error_summary=self._safe_error_summary(error))
                raise EnhancementError(error.code, error.message, details={"receipt": self._receipt(updated)}, retryable=error.retryable) from None
            except Exception:
                updated = ledger.transition(job_id, expected_states={"submitting"}, state="recovery_required", at=self._format_time(evaluated_at), attempts=attempts, error_code=EnhancementErrorCode.PROVIDER_REJECTED.value, retryable=False, error_summary="enhancement adapter failed unexpectedly")
                raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "enhancement adapter failed unexpectedly", details={"receipt": self._receipt(updated)}) from None
        if not provider_job_id:
            record = ledger.transition(job_id, expected_states={"submitting"}, state="recovery_required", at=self._format_time(evaluated_at), attempts=attempts, error_code=EnhancementErrorCode.PROVIDER_RETRY_EXHAUSTED.value, retryable=True, error_summary="enhancement submit retry budget is exhausted")
            raise EnhancementError(EnhancementErrorCode.PROVIDER_RETRY_EXHAUSTED, "enhancement submit retry budget is exhausted", details={"receipt": self._receipt(record)}, retryable=True)
        record = ledger.transition(job_id, expected_states={"submitting"}, state="submitted", at=self._format_time(evaluated_at), attempts=attempts, provider_job_id=provider_job_id)
        return self._result(record)

    def poll_enhancement(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        adapter, ledger = self._dependencies()
        record = ledger.get(job_id)
        if record["state"] not in ACTIVE_STATES:
            raise EnhancementError(EnhancementErrorCode.INVALID_TRANSITION, "only active enhancement jobs may be polled")
        evaluated_at = self._now(now)
        submitted_at = datetime.fromisoformat(str(record["submitted_at"]).replace("Z", "+00:00"))
        if (evaluated_at - submitted_at).total_seconds() >= int(record["budget"]["timeout_seconds"]):
            try:
                adapter.cancel(str(record["provider_job_id"]))
            except Exception:
                updated = ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=EnhancementErrorCode.PROVIDER_REJECTED.value, retryable=False, error_summary="enhancement timeout cancellation failed")
                raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "enhancement timeout cancellation failed", details={"receipt": self._receipt(updated)}) from None
            return self._result(ledger.transition(job_id, expected_states=ACTIVE_STATES, state="timed_out", at=self._format_time(evaluated_at), error_code=EnhancementErrorCode.PROVIDER_RETRY_EXHAUSTED.value, retryable=False, error_summary="enhancement execution timed out"))
        result: Mapping[str, object] | None = None
        poll_attempts = 0
        while poll_attempts < int(record["budget"]["max_attempts"]):
            poll_attempts += 1
            try:
                candidate = adapter.poll(str(record["provider_job_id"]))
                if not isinstance(candidate, Mapping):
                    raise AdapterFailure("PROVIDER_REJECTED", "adapter returned invalid poll data", retryable=False)
                result = candidate
                break
            except AdapterFailure as error:
                if not error.retryable:
                    updated = ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=self._adapter_code(error).value, retryable=False, error_summary=self._safe_error_summary(error))
                    raise EnhancementError(self._adapter_code(error), str(error), details={"receipt": self._receipt(updated)}) from None
            except Exception:
                updated = ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=EnhancementErrorCode.PROVIDER_REJECTED.value, retryable=False, error_summary="enhancement adapter failed unexpectedly")
                raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "enhancement adapter failed unexpectedly", details={"receipt": self._receipt(updated)}) from None
        if result is None:
            updated = ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), poll_attempts=poll_attempts, error_code=EnhancementErrorCode.PROVIDER_RETRY_EXHAUSTED.value, retryable=True, error_summary="enhancement poll retry budget is exhausted")
            raise EnhancementError(EnhancementErrorCode.PROVIDER_RETRY_EXHAUSTED, "enhancement poll retry budget is exhausted", details={"receipt": self._receipt(updated)}, retryable=True)
        state = result.get("state")
        mapping = {"running": "polling", "succeeded": "succeeded", "failed": "failed", "cancelled": "cancelled"}
        if state not in mapping:
            updated = ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=EnhancementErrorCode.PROVIDER_REJECTED.value, retryable=False, error_summary="adapter returned an unsupported state")
            raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "adapter returned an unsupported state", details={"receipt": self._receipt(updated)})
        changes: dict[str, object] = {"poll_attempts": poll_attempts}
        if state == "failed":
            changes.update({
                "error_code": EnhancementErrorCode.PROVIDER_REJECTED.value,
                "retryable": False,
                "error_summary": "adapter reported enhancement failure",
            })
        return self._result(ledger.transition(job_id, expected_states=ACTIVE_STATES, state=mapping[str(state)], at=self._format_time(evaluated_at), **changes))

    def cancel_enhancement(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        adapter, ledger = self._dependencies()
        record = ledger.get(job_id)
        if record["state"] == "cancelled":
            return self._result(record, replayed=True)
        if record["state"] not in ACTIVE_STATES:
            raise EnhancementError(EnhancementErrorCode.INVALID_TRANSITION, "only active enhancement jobs may be cancelled")
        evaluated_at = self._now(now)
        try:
            adapter.cancel(str(record["provider_job_id"]))
        except AdapterFailure as error:
            updated = ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=self._adapter_code(error).value, retryable=error.retryable, error_summary=self._safe_error_summary(error))
            raise EnhancementError(self._adapter_code(error), str(error), details={"receipt": self._receipt(updated)}, retryable=error.retryable) from None
        except Exception:
            updated = ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=EnhancementErrorCode.PROVIDER_REJECTED.value, retryable=False, error_summary="enhancement adapter failed unexpectedly")
            raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "enhancement adapter failed unexpectedly", details={"receipt": self._receipt(updated)}) from None
        return self._result(ledger.transition(job_id, expected_states=ACTIVE_STATES, state="cancelled", at=self._format_time(evaluated_at)))

    def download_enhancement(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        adapter, ledger = self._dependencies()
        record = ledger.get(job_id)
        if record["state"] != "succeeded":
            raise EnhancementError(EnhancementErrorCode.INVALID_TRANSITION, "only succeeded enhancement jobs may be downloaded")
        evaluated_at = self._now(now)
        try:
            artifact = adapter.download(str(record["provider_job_id"]))
        except AdapterFailure as error:
            self._fail_download(
                ledger,
                record,
                code=self._adapter_code(error),
                message=str(error),
                evaluated_at=evaluated_at,
                retryable=error.retryable,
            )
        except Exception:
            self._fail_download(
                ledger,
                record,
                code=EnhancementErrorCode.PROVIDER_REJECTED,
                message="enhancement adapter failed unexpectedly",
                evaluated_at=evaluated_at,
            )
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("content"), bytes):
            self._fail_download(
                ledger,
                record,
                code=EnhancementErrorCode.PROVIDER_REJECTED,
                message="adapter returned invalid enhancement bytes",
                evaluated_at=evaluated_at,
            )
        content = artifact["content"]
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if artifact.get("sha256") != actual:
            self._fail_download(
                ledger,
                record,
                code=EnhancementErrorCode.DOWNLOAD_INTEGRITY_FAILED,
                message="enhancement artifact digest mismatch",
                evaluated_at=evaluated_at,
            )
        source_uri = artifact.get("source_uri")
        if not isinstance(source_uri, str) or contains_sensitive_text(source_uri):
            self._fail_download(
                ledger,
                record,
                code=EnhancementErrorCode.PROVIDER_REJECTED,
                message="enhancement artifact source is invalid",
                evaluated_at=evaluated_at,
            )
        output = {
            "media_type": artifact.get("media_type"),
            "size_bytes": len(content),
            "sha256": actual,
            "source_uri_digest": content_digest(source_uri),
            "contract_status": CONTRACT_STATUS,
        }
        record = ledger.transition(job_id, expected_states={"succeeded"}, state="downloaded", at=self._format_time(evaluated_at), output=output)
        return self._result(record)

    def _fail_download(
        self,
        ledger: InMemoryEnhancementLedger,
        record: Mapping[str, object],
        *,
        code: EnhancementErrorCode,
        message: str,
        evaluated_at: datetime,
        retryable: bool = False,
    ) -> None:
        updated = ledger.transition(
            str(record["job_id"]),
            expected_states={"succeeded"},
            state="failed",
            at=self._format_time(evaluated_at),
            error_code=code.value,
            retryable=retryable,
            error_summary=self._safe_error_summary(RuntimeError(message)),
        )
        raise EnhancementError(
            code,
            message,
            details={"receipt": self._receipt(updated)},
            retryable=retryable,
        )

    def recover_enhancement(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        del now
        _, ledger = self._dependencies()
        return self._result(ledger.get(job_id), recovered=True)

    def _dependencies(self) -> tuple[VideoEnhancementAdapter, InMemoryEnhancementLedger]:
        adapter = self._adapter
        ledger = self._ledger
        methods = ("submit", "poll", "cancel", "download")
        ledger_methods = ("reserve", "get", "transition", "active_count", "recoverable", "wait_for_submission")
        if (
            adapter is None
            or ledger is None
            or type(adapter) not in {FakeVideoEnhancementAdapter, RejectingVideoEnhancementAdapter}
            or getattr(adapter, "execution_mode", None) != "offline_adapter"
            or getattr(adapter, "network_performed", None) is not False
            or not all(hasattr(adapter, item) for item in methods)
            or not all(hasattr(ledger, item) for item in ledger_methods)
        ):
            raise EnhancementError(EnhancementErrorCode.NETWORK_BLOCKED, "an explicit offline enhancement adapter and ledger are required")
        return adapter, ledger

    def _result(self, record: Mapping[str, object], *, replayed: bool = False, recovered: bool = False) -> dict[str, object]:
        return snapshot({
            "job_id": record["job_id"],
            "state": record["state"],
            "history": record["history"],
            "replayed": replayed,
            "recovered": recovered,
            "provider_network_performed": False,
            "provider_execution_mode": "offline_adapter",
            "receipt": self._receipt(record),
        })

    @staticmethod
    def _receipt(record: Mapping[str, object]) -> dict[str, object]:
        profile = record["workflow_profile"]
        provider_job_id = str(record.get("provider_job_id", ""))
        history = record["history"]
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "contract_status": CONTRACT_STATUS,
            "authorization_id": record["authorization"]["authorization_id"],
            "work_item_id": record["authorization"]["work_item_id"],
            "request_hash": record["request_hash"],
            "idempotency_key": record["idempotency_key"],
            "job_id": record["job_id"],
            "provider_job_id_digest": content_digest(provider_job_id) if provider_job_id else None,
            "input_summary": record["input_summary"],
            "workflow_profile": {
                "profile_id": profile["profile_id"],
                "profile_version": profile["profile_version"],
                "profile_digest": profile["profile_digest"],
            },
            "operations": record["operations"],
            "cost_estimate": record["cost_estimate"],
            "state": record["state"],
            "attempts": record.get("attempts", 0),
            "recorded_at": history[-1]["at"],
            "state_history": [item["state"] for item in history],
            "output": record.get("output"),
            "provider_network_performed": False,
            "provider_execution_performed": bool(provider_job_id),
            "error_code": record.get("error_code"),
            "retryable": record.get("retryable", False),
            "error_summary": record.get("error_summary"),
        }
        receipt["receipt_id"] = "receipt-" + content_digest(receipt).removeprefix("sha256:")[:24]
        return snapshot(sanitize_sensitive(receipt))

    @staticmethod
    def _safe_error_summary(error: BaseException) -> str:
        value = sanitize_sensitive(str(error))
        return value if isinstance(value, str) else "enhancement adapter rejected the request"

    @staticmethod
    def _adapter_code(error: AdapterFailure) -> EnhancementErrorCode:
        return EnhancementErrorCode.PROVIDER_REJECTED

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        evaluated_at = value or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "now must be timezone-aware")
        return evaluated_at.astimezone(timezone.utc)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")
