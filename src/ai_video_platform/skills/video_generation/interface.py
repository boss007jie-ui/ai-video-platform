"""Public offline Video Generation preflight and execution state machine."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import re

from .adapters import AdapterFailure, VideoProviderAdapter
from .errors import GenerationError, GenerationErrorCode
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
        existing = ledger.idempotent(str(inspected["idempotency_key"]), str(inspected["request_hash"]))
        if existing is not None:
            error_code = existing.get("error_code")
            if existing.get("state") == "failed" and isinstance(error_code, str):
                try:
                    code = GenerationErrorCode(error_code)
                except ValueError:
                    code = GenerationErrorCode.PROVIDER_REJECTED
                raise GenerationError(code, "Previously recorded execution failed", retryable=bool(existing.get("retryable")))
            return self._result(existing, replayed=True)
        budget = inspected["budget"]
        evaluated_at = self._now(now)
        job_id = "job-" + content_digest({
            "request_hash": inspected["request_hash"],
            "idempotency_key": inspected["idempotency_key"],
        }).removeprefix("sha256:")[:20]
        ledger.reserve({
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
        attempts = 0
        provider_job_id = ""
        while attempts < int(budget["max_attempts"]):
            attempts += 1
            try:
                provider_job_id = adapter.submit(inspected)
                break
            except AdapterFailure as exc:
                if not exc.retryable:
                    code = {
                        "PROVIDER_REJECTED": GenerationErrorCode.PROVIDER_REJECTED,
                        "NETWORK_BLOCKED": GenerationErrorCode.NETWORK_BLOCKED,
                    }.get(exc.code, GenerationErrorCode.PROVIDER_REJECTED)
                    ledger.update(job_id, state="failed", attempts=attempts, error_code=code.value, retryable=False)
                    raise GenerationError(code, str(exc), retryable=False) from None
            except Exception:
                ledger.update(
                    job_id,
                    state="failed",
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
            ledger.update(
                job_id,
                state="failed",
                attempts=attempts,
                error_code=GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED.value,
                retryable=True,
            )
            raise GenerationError(
                GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED,
                "Synthetic Provider retry budget is exhausted",
                retryable=True,
            )
        record = ledger.update(
            job_id,
            provider_job_id=provider_job_id,
            state="submitted",
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
            except Exception:
                pass
            return self._result(ledger.update(job_id, state="timed_out"))
        try:
            provider_result = adapter.poll(str(record["provider_job_id"]))
        except AdapterFailure as exc:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, str(exc), retryable=exc.retryable) from None
        except Exception:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider adapter failed unexpectedly") from None
        state = provider_result.get("state")
        if state not in {"running", "succeeded", "failed", "cancelled"}:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider returned an unsupported state")
        return self._result(ledger.update(job_id, state=state))

    def cancel_video(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        adapter, ledger = self._dependencies()
        record = ledger.get(job_id)
        if record["state"] not in ACTIVE_STATES:
            raise GenerationError(GenerationErrorCode.INVALID_TRANSITION, "Only active video jobs may be cancelled")
        try:
            adapter.cancel(str(record["provider_job_id"]))
        except AdapterFailure as exc:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, str(exc), retryable=exc.retryable) from None
        except Exception:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider adapter failed unexpectedly") from None
        return self._result(ledger.update(job_id, state="cancelled"))

    def download_video(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        adapter, ledger = self._dependencies()
        record = ledger.get(job_id)
        if record["state"] != "succeeded":
            raise GenerationError(GenerationErrorCode.INVALID_TRANSITION, "Only succeeded video jobs may be downloaded")
        try:
            artifact = adapter.download(str(record["provider_job_id"]))
        except AdapterFailure as exc:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, str(exc), retryable=exc.retryable) from None
        except Exception:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Provider adapter failed unexpectedly") from None
        content = artifact.get("content")
        expected = artifact.get("sha256")
        uri = artifact.get("uri")
        if not isinstance(content, bytes) or not isinstance(expected, str) or not isinstance(uri, str) or re.fullmatch(r"memory://[A-Za-z0-9._/-]+", uri) is None:
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
            "media_type": "video/mp4",
            "library_write_performed": False,
        }
        return self._result(ledger.update(job_id, state="downloaded", asset_manifest_request=manifest_request))

    def recover_video(self, job_id: str, *, now: datetime | None = None) -> dict[str, object]:
        _, ledger = self._dependencies()
        record = ledger.get(job_id)
        if record["state"] == "submitting" and not record.get("provider_job_id"):
            return self._result(ledger.update(job_id, state="failed"))
        if record["state"] in ACTIVE_STATES:
            return self.poll_video(job_id, now=now)
        return self._result(record)

    def _dependencies(self) -> tuple[VideoProviderAdapter, InMemoryVideoExecutionLedger]:
        adapter = self._adapter
        ledger = self._ledger
        adapter_methods = ("submit", "poll", "cancel", "download")
        ledger_methods = ("idempotent", "reserve", "get", "update")
        if adapter is None or ledger is None or not all(hasattr(adapter, name) for name in adapter_methods) or not all(hasattr(ledger, name) for name in ledger_methods):
            raise GenerationError(GenerationErrorCode.NETWORK_BLOCKED, "An authorized offline adapter and ledger are required")
        return adapter, ledger

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        evaluated_at = value or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            raise GenerationError(GenerationErrorCode.INVALID_INPUT, "now must be timezone-aware")
        return evaluated_at.astimezone(timezone.utc)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _result(record: Mapping[str, object], *, replayed: bool = False) -> dict[str, object]:
        public = {
            key: value for key, value in record.items()
            if key not in {"provider_job_id", "budget", "output", "request_hash", "idempotency_key"}
        }
        public.update({
            "replayed": replayed,
            "provider_network_performed": False,
            "provider_execution_mode": "offline_adapter",
        })
        return snapshot(public)
