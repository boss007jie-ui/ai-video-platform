"""Public offline Video Generation preflight and execution state machine."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import re

from .adapters import AdapterFailure, VideoProviderAdapter
from .errors import GenerationError, GenerationErrorCode, contains_sensitive_text
from .ledger import ACTIVE_STATES, InMemoryVideoExecutionLedger
from .models import CONTRACT_STATUS, content_digest, parse_utc, snapshot
from .preflight import GenerationPreflight


class VideoGenerationInterface:
    def __init__(
        self,
        *,
        adapter: VideoProviderAdapter | object | None = None,
        ledger: InMemoryVideoExecutionLedger | object | None = None,
    ) -> None:
        self._preflight = GenerationPreflight()
        self._adapter = adapter
        self._ledger = ledger

    def inspect_video_request(
        self,
        request: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        return self._preflight.inspect(request, now=now)

    def submit_video(self, request: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
        inspected = self.inspect_video_request(request, now=now)
        adapter, ledger = self._dependencies()
        budget = inspected["budget"]
        evaluated_at = self._now(now)
        job_id = "job-" + content_digest({
            "request_hash": inspected["request_hash"],
            "idempotency_key": inspected["idempotency_key"],
        }).removeprefix("sha256:")[:20]
        reserved, created = ledger.reserve({
            "job_id": job_id,
            "provider_job_id": "",
            "request_hash": inspected["request_hash"],
            "idempotency_key": inspected["idempotency_key"],
            "package_id": inspected["package_id"],
            "package_digest": inspected["package_digest"],
            "budget": budget,
            "output": inspected["output"],
            "state": "submitting",
            "attempts": 0,
            "submitted_at": self._format_time(evaluated_at),
        },
            max_requests=int(budget["max_requests"]),
            max_concurrency=int(budget["max_concurrency"]),
        )
        if not created:
            if reserved.get("state") == "submitting":
                reserved = ledger.wait_for_submission(job_id, min(float(budget["timeout_seconds"]), 30.0))
            error_code = reserved.get("error_code")
            if reserved.get("state") in {"failed", "recovery_required"} and isinstance(error_code, str):
                try:
                    code = GenerationErrorCode(error_code)
                except ValueError:
                    code = GenerationErrorCode.PROVIDER_REJECTED
                raise GenerationError(code, "Previously recorded execution failed", retryable=bool(reserved.get("retryable")))
            return self._result(reserved, replayed=True)
        attempts = 0
        provider_job_id = ""
        while attempts < int(budget["max_attempts"]):
            attempts += 1
            try:
                candidate_job_id = adapter.submit(inspected)
                if not isinstance(candidate_job_id, str) or not candidate_job_id.strip() or contains_sensitive_text(candidate_job_id):
                    raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider returned an invalid job identity")
                provider_job_id = candidate_job_id
                break
            except AdapterFailure as exc:
                if not exc.retryable:
                    code = self._adapter_error_code(exc)
                    terminal_rejection = exc.code in {"PROVIDER_REJECTED", "NETWORK_BLOCKED"}
                    ledger.transition(job_id, expected_states={"submitting"}, state="failed" if terminal_rejection else "recovery_required", at=self._format_time(evaluated_at), attempts=attempts, error_code=code.value, retryable=False)
                    raise GenerationError(code, str(exc), retryable=False) from None
            except GenerationError:
                ledger.transition(job_id, expected_states={"submitting"}, state="recovery_required", at=self._format_time(evaluated_at), attempts=attempts, error_code=GenerationErrorCode.PROVIDER_REJECTED.value, retryable=False)
                raise
            except Exception:
                ledger.transition(
                    job_id,
                    expected_states={"submitting"},
                    state="recovery_required",
                    at=self._format_time(evaluated_at),
                    attempts=attempts,
                    error_code=GenerationErrorCode.PROVIDER_REJECTED.value,
                    retryable=False,
                )
                raise GenerationError(
                    GenerationErrorCode.PROVIDER_REJECTED,
                    "Provider adapter failed unexpectedly",
                    retryable=False,
                ) from None
        if not provider_job_id:
            ledger.transition(
                job_id,
                expected_states={"submitting"},
                state="recovery_required",
                at=self._format_time(evaluated_at),
                attempts=attempts,
                error_code=GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED.value,
                retryable=True,
            )
            raise GenerationError(
                GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED,
                "Synthetic Provider retry budget is exhausted",
                retryable=True,
            )
        record = ledger.transition(
            job_id,
            expected_states={"submitting"},
            provider_job_id=provider_job_id,
            state="submitted",
            at=self._format_time(evaluated_at),
            attempts=attempts,
        )
        return self._result(record, replayed=False)

    def poll_video(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        adapter, ledger = self._dependencies()
        record = ledger.get(job_id)
        if record["state"] not in ACTIVE_STATES:
            raise GenerationError(GenerationErrorCode.INVALID_TRANSITION, "Only active video jobs may be polled")
        evaluated_at = self._now(now)
        submitted_at = parse_utc(record["submitted_at"], "submitted_at")
        if (evaluated_at - submitted_at).total_seconds() >= int(record["budget"]["timeout_seconds"]):
            try:
                adapter.cancel(str(record["provider_job_id"]))
            except AdapterFailure as exc:
                ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=self._adapter_error_code(exc).value)
                raise GenerationError(self._adapter_error_code(exc), str(exc), retryable=exc.retryable) from None
            except Exception:
                ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=GenerationErrorCode.PROVIDER_REJECTED.value)
                raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider adapter failed unexpectedly") from None
            return self._result(ledger.transition(job_id, expected_states=ACTIVE_STATES, state="timed_out", at=self._format_time(evaluated_at)))
        poll_attempts = 0
        provider_result: Mapping[str, object] | None = None
        while poll_attempts < int(record["budget"]["max_attempts"]):
            poll_attempts += 1
            try:
                candidate = adapter.poll(str(record["provider_job_id"]))
                if not isinstance(candidate, Mapping):
                    ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=GenerationErrorCode.PROVIDER_REJECTED.value)
                    raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider returned malformed poll data")
                provider_result = candidate
                break
            except AdapterFailure as exc:
                if not exc.retryable:
                    code = self._adapter_error_code(exc)
                    ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=code.value)
                    raise GenerationError(code, str(exc), retryable=False) from None
            except GenerationError:
                raise
            except Exception:
                ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=GenerationErrorCode.PROVIDER_REJECTED.value)
                raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider adapter failed unexpectedly") from None
        if provider_result is None:
            ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED.value, poll_attempts=poll_attempts)
            raise GenerationError(GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED, "Provider poll retry budget is exhausted", retryable=True)
        state = provider_result.get("state")
        if state not in {"running", "succeeded", "failed", "cancelled"}:
            ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=GenerationErrorCode.PROVIDER_REJECTED.value)
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider returned an unsupported state")
        changes: dict[str, object] = {"poll_attempts": poll_attempts}
        cost_units = provider_result.get("cost_units")
        if cost_units is not None:
            if isinstance(cost_units, bool) or not isinstance(cost_units, (int, float)) or cost_units < 0:
                ledger.transition(job_id, expected_states=ACTIVE_STATES, state="recovery_required", at=self._format_time(evaluated_at), error_code=GenerationErrorCode.PROVIDER_REJECTED.value)
                raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider returned invalid cost data")
            changes["provider_cost_units"] = cost_units
            if cost_units > float(record["budget"]["max_cost_units"]):
                ledger.transition(
                    job_id,
                    expected_states=ACTIVE_STATES,
                    state="failed",
                    at=self._format_time(evaluated_at),
                    error_code=GenerationErrorCode.BUDGET_EXCEEDED.value,
                    **changes,
                )
                raise GenerationError(
                    GenerationErrorCode.BUDGET_EXCEEDED,
                    "Provider actual cost exceeds the approved budget",
                )
        if record["state"] != "polling":
            record = ledger.transition(
                job_id,
                expected_states=ACTIVE_STATES,
                state="polling",
                at=self._format_time(evaluated_at),
                **changes,
            )
        elif state == "running":
            record = ledger.transition(
                job_id,
                expected_states={"polling"},
                state="polling",
                at=self._format_time(evaluated_at),
                **changes,
            )
        if state == "running":
            return self._result(record)
        return self._result(ledger.transition(
            job_id,
            expected_states={"polling"},
            state=str(state),
            at=self._format_time(evaluated_at),
            **changes,
        ))

    def cancel_video(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        adapter, ledger = self._dependencies()
        record = ledger.get(job_id)
        if record["state"] == "cancelled":
            return self._result(record, replayed=True)
        if record["state"] not in ACTIVE_STATES:
            raise GenerationError(GenerationErrorCode.INVALID_TRANSITION, "Only active video jobs may be cancelled")
        evaluated_at = self._now(now)
        try:
            adapter.cancel(str(record["provider_job_id"]))
        except AdapterFailure as exc:
            raise GenerationError(self._adapter_error_code(exc), str(exc), retryable=exc.retryable) from None
        except Exception:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider adapter failed unexpectedly") from None
        return self._result(ledger.transition(job_id, expected_states=ACTIVE_STATES, state="cancelled", at=self._format_time(evaluated_at)))

    def download_video(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        adapter, ledger = self._dependencies()
        record = ledger.get(job_id)
        if record["state"] != "succeeded":
            raise GenerationError(GenerationErrorCode.INVALID_TRANSITION, "Only succeeded video jobs may be downloaded")
        try:
            artifact = adapter.download(str(record["provider_job_id"]))
        except AdapterFailure as exc:
            raise GenerationError(self._adapter_error_code(exc), str(exc), retryable=exc.retryable) from None
        except Exception:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider adapter failed unexpectedly") from None
        if not isinstance(artifact, Mapping):
            raise GenerationError(GenerationErrorCode.DOWNLOAD_INTEGRITY_FAILED, "Downloaded artifact metadata is invalid")
        content = artifact.get("content")
        expected = artifact.get("sha256")
        uri = artifact.get("uri")
        content_type = artifact.get("content_type")
        if not isinstance(content, bytes) or not isinstance(expected, str) or not isinstance(uri, str) or contains_sensitive_text(uri) or re.fullmatch(r"(?:memory|kie)://[A-Za-z0-9._/-]+", uri) is None or content_type != "video/mp4":
            raise GenerationError(GenerationErrorCode.DOWNLOAD_INTEGRITY_FAILED, "Downloaded artifact metadata is invalid")
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise GenerationError(GenerationErrorCode.DOWNLOAD_INTEGRITY_FAILED, "Downloaded artifact digest mismatch")
        manifest_request = {
            "artifact_name": "AssetManifestRequest",
            "schema_version": "0.1.0",
            "contract_status": CONTRACT_STATUS,
            "source_job_id": job_id,
            "uri": uri,
            "sha256": actual,
            "media_type": content_type,
            "size_bytes": len(content),
            "provenance": {"source_job_id": job_id, "execution_mode": self._execution_mode()},
            "library_write_performed": False,
        }
        evaluated_at = self._now(now)
        return self._result(ledger.transition(job_id, expected_states={"succeeded"}, state="downloaded", at=self._format_time(evaluated_at), asset_manifest_request=manifest_request))

    def recover_video(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        del now
        _, ledger = self._dependencies()
        record = ledger.get(job_id)
        return self._result(record, recovered=True)

    def _dependencies(self) -> tuple[VideoProviderAdapter, InMemoryVideoExecutionLedger]:
        adapter = self._adapter
        ledger = self._ledger
        adapter_methods = ("submit", "poll", "cancel", "download")
        ledger_methods = ("reserve", "get", "transition", "active_count", "recoverable", "wait_for_submission")
        if adapter is None or ledger is None or not all(hasattr(adapter, name) for name in adapter_methods) or not all(hasattr(ledger, name) for name in ledger_methods):
            raise GenerationError(GenerationErrorCode.NETWORK_BLOCKED, "An authorized offline adapter and ledger are required")
        return adapter, ledger

    @staticmethod
    def _adapter_error_code(error: AdapterFailure) -> GenerationErrorCode:
        return GenerationErrorCode.NETWORK_BLOCKED if error.code == "NETWORK_BLOCKED" else GenerationErrorCode.PROVIDER_REJECTED

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        evaluated_at = value or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            raise GenerationError(GenerationErrorCode.INVALID_INPUT, "now must be timezone-aware")
        return evaluated_at.astimezone(timezone.utc)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    def _execution_mode(self) -> str:
        value = getattr(self._adapter, "execution_mode", "offline_adapter")
        return value if value in {"offline_adapter", "kie_production"} else "offline_adapter"

    def _result(self, record: Mapping[str, object], *, replayed: bool = False, recovered: bool = False) -> dict[str, object]:
        public = {
            key: value for key, value in record.items()
            if key not in {"provider_job_id", "budget", "output", "request_hash", "idempotency_key"}
        }
        public.update({
            "replayed": replayed,
            "recovered": recovered,
            "provider_network_performed": bool(getattr(self._adapter, "network_performed", False)),
            "provider_execution_mode": self._execution_mode(),
        })
        return snapshot(public)
