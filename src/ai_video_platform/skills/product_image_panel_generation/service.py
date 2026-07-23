"""Application service entry point for safe image and panel generation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from queue import Empty, Queue
from threading import BoundedSemaphore, Lock, Thread
import time
from typing import Callable, Iterable

from ai_video_platform.contracts import ProducerIdentity, build_envelope, validate_envelope
from ai_video_platform.contracts.serialization import freeze_json

from .adapters import ImageProviderAdapter, ProviderAsset, ProviderInvocation
from .errors import ImagePanelError, ImagePanelErrorCode
from .models import (
    CancellationToken,
    GeneratedAsset,
    GenerationCommand,
    GenerationOutcome,
    GenerationRecord,
    GenerationRequest,
    GenerationStatus,
    ItemGenerationRecord,
    ItemStatus,
    ModelProfile,
    PreflightInspection,
)
from .preflight import SKILL_ID, inspect_request
from .prompting import compile_prompt


SKILL_VERSION = "0.1.0"


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ImagePanelService:
    def __init__(
        self,
        *,
        provider: ImageProviderAdapter,
        profiles: Iterable[ModelProfile],
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        max_concurrency: int = 1,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if not isinstance(provider, ImageProviderAdapter):
            raise TypeError("provider must implement ImageProviderAdapter")
        self._provider = provider
        self._profiles = {profile.profile_id: profile for profile in profiles}
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or time.sleep
        self._max_concurrency = max_concurrency
        self._slots = BoundedSemaphore(max_concurrency)
        self._ledger_lock = Lock()
        self._ledger: dict[str, tuple[str, GenerationOutcome | None]] = {}

    def inspect_generation_request(self, request: GenerationRequest) -> PreflightInspection:
        return inspect_request(request, profiles=self._profiles, now=self._now())

    def generate_product_image(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> GenerationOutcome:
        if request.command is not GenerationCommand.GENERATE_PRODUCT_IMAGE:
            raise ImagePanelError(
                ImagePanelErrorCode.SKILL_BINDING_INVALID,
                "Request command is not generate-product-image",
                field_paths=("command",),
            )
        return self._generate(request, cancellation=cancellation)

    def generate_panel(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> GenerationOutcome:
        if request.command is not GenerationCommand.GENERATE_PANEL:
            raise ImagePanelError(
                ImagePanelErrorCode.SKILL_BINDING_INVALID,
                "Request command is not generate-panel",
                field_paths=("command",),
            )
        return self._generate(request, cancellation=cancellation)

    def _reserve(self, request: GenerationRequest) -> GenerationOutcome | None:
        with self._ledger_lock:
            existing = self._ledger.get(request.idempotency_key)
            if existing is not None:
                digest, outcome = existing
                if digest != request.request_hash:
                    raise ImagePanelError(
                        ImagePanelErrorCode.IDEMPOTENCY_CONFLICT,
                        "Idempotency key was reused with a different request hash",
                        category="conflict",
                        field_paths=("idempotency_key", "request_hash"),
                    )
                if outcome is None:
                    raise ImagePanelError(
                        ImagePanelErrorCode.IDEMPOTENCY_IN_PROGRESS,
                        "The idempotent request is already in progress",
                        category="state",
                        retryable=True,
                    )
                return replace(outcome, replayed=True)
            self._ledger[request.idempotency_key] = (request.request_hash, None)
            return None

    def _release_reservation(self, request: GenerationRequest) -> None:
        with self._ledger_lock:
            current = self._ledger.get(request.idempotency_key)
            if current == (request.request_hash, None):
                del self._ledger[request.idempotency_key]

    def _record_outcome(self, request: GenerationRequest, outcome: GenerationOutcome) -> None:
        with self._ledger_lock:
            self._ledger[request.idempotency_key] = (request.request_hash, outcome)

    def _generate(self, request: GenerationRequest, *, cancellation: CancellationToken | None) -> GenerationOutcome:
        self.inspect_generation_request(request)
        if request.budget is not None and request.budget.max_concurrency > self._max_concurrency:
            raise ImagePanelError(
                ImagePanelErrorCode.CONCURRENCY_LIMIT_EXCEEDED,
                "Requested concurrency exceeds the configured Skill limit",
                category="authorization",
                field_paths=("budget.max_concurrency",),
            )
        replay = self._reserve(request)
        if replay is not None:
            return replay
        if not self._slots.acquire(blocking=False):
            self._release_reservation(request)
            raise ImagePanelError(
                ImagePanelErrorCode.CONCURRENCY_LIMIT_EXCEEDED,
                "Skill concurrency limit is reached",
                category="state",
                retryable=True,
            )
        try:
            outcome = self._execute(request, cancellation or CancellationToken())
            self._record_outcome(request, outcome)
            return outcome
        except BaseException:
            self._release_reservation(request)
            raise
        finally:
            self._slots.release()

    def _execute(self, request: GenerationRequest, cancellation: CancellationToken) -> GenerationOutcome:
        started_at = _utc_text(self._now())
        profile = self._profiles[request.model_profile_id]
        budget = request.budget
        if budget is None:  # narrowed by preflight; keeps the Provider path fail closed
            raise ImagePanelError(ImagePanelErrorCode.BUDGET_REQUIRED, "Generation budget is required")
        provider_id = self._provider.provider_id
        if provider_id != profile.provider_id:
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
                "Configured adapter does not match the approved model profile",
                category="authorization",
            )

        assets: list[GeneratedAsset] = []
        item_records: list[ItemGenerationRecord] = []
        for item in request.items:
            if cancellation.cancelled:
                item_records.append(ItemGenerationRecord(item.item_id, ItemStatus.CANCELLED, 0, 0))
                continue
            attempts = 0
            item_error: ImagePanelError | None = None
            generated: GeneratedAsset | None = None
            while attempts < budget.max_attempts:
                if cancellation.cancelled:
                    item_error = ImagePanelError(ImagePanelErrorCode.CANCELLED, "Generation was cancelled", category="state")
                    break
                attempts += 1
                invocation = ProviderInvocation(
                    request_id=request.request_id,
                    request_hash=request.request_hash,
                    item=item,
                    profile=profile,
                    compiled_prompt=compile_prompt(request, item),
                    attempt=attempts,
                    timeout_seconds=budget.timeout_seconds,
                )
                try:
                    provider_asset = self._invoke_provider(invocation, cancellation)
                    if not isinstance(provider_asset, ProviderAsset):
                        raise TypeError("Adapter returned an invalid result type")
                    digest = hashlib.sha256(provider_asset.content).hexdigest()
                    generated = GeneratedAsset(
                        asset_id=f"asset:{request.request_id}:{item.item_id}",
                        item_id=item.item_id,
                        role=item.role,
                        uri=f"memory://offline/{request.request_id}/{item.item_id}",
                        content_type=provider_asset.content_type,
                        sha256=digest,
                        byte_size=len(provider_asset.content),
                        width=provider_asset.width or item.width,
                        height=provider_asset.height or item.height,
                        derived_from=tuple(item.input_asset_ids),
                        provider_asset_id=provider_asset.provider_asset_id,
                        provider_metadata=provider_asset.provider_metadata,
                    )
                    break
                except ImagePanelError as exc:
                    safe_message = {
                        ImagePanelErrorCode.CANCELLED: "Generation was cancelled",
                        ImagePanelErrorCode.PROVIDER_TIMEOUT: "Provider attempt timed out",
                        ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED: "Provider execution is not authorized",
                    }.get(exc.code, "Provider attempt failed")
                    item_error = ImagePanelError(
                        exc.code,
                        safe_message,
                        category=exc.category,
                        retryable=exc.retryable,
                        details=exc.details,
                    )
                    if exc.code is ImagePanelErrorCode.CANCELLED or not exc.retryable or attempts >= budget.max_attempts:
                        break
                    self._sleep(min(0.05 * (2 ** (attempts - 1)), 1.0))
                except Exception as exc:
                    item_error = ImagePanelError(
                        ImagePanelErrorCode.PROVIDER_FAILED,
                        "Provider adapter failed unexpectedly",
                        category="provider",
                        details={"cause_type": type(exc).__name__},
                    )
                    break
            cost = attempts * profile.cost_per_attempt
            if generated is not None:
                assets.append(generated)
                item_records.append(
                    ItemGenerationRecord(item.item_id, ItemStatus.COMPLETED, attempts, cost, asset_id=generated.asset_id)
                )
            elif item_error is not None and item_error.code is ImagePanelErrorCode.CANCELLED:
                item_records.append(
                    ItemGenerationRecord(item.item_id, ItemStatus.CANCELLED, attempts, cost, error=freeze_json(item_error.to_dict()))
                )
            else:
                safe_error = item_error or ImagePanelError(ImagePanelErrorCode.PROVIDER_FAILED, "Provider attempt failed", category="provider")
                item_records.append(
                    ItemGenerationRecord(item.item_id, ItemStatus.FAILED, attempts, cost, error=freeze_json(safe_error.to_dict()))
                )

        completed_count = sum(item.status is ItemStatus.COMPLETED for item in item_records)
        cancelled_count = sum(item.status is ItemStatus.CANCELLED for item in item_records)
        if completed_count == len(item_records):
            status = GenerationStatus.COMPLETED
        elif completed_count:
            status = GenerationStatus.PARTIAL_FAILURE
        elif cancelled_count == len(item_records):
            status = GenerationStatus.CANCELLED
        else:
            status = GenerationStatus.FAILED
        completed_at = _utc_text(self._now())
        record = GenerationRecord(
            record_id=f"generation-record:{request.request_id}",
            request_id=request.request_id,
            request_hash=request.request_hash,
            status=status,
            product_id=request.product_id,
            profile_id=profile.profile_id,
            provider_id=profile.provider_id,
            model_id=profile.model_id,
            model_version=profile.version,
            started_at=started_at,
            completed_at=completed_at,
            total_attempts=sum(item.attempts for item in item_records),
            total_cost_units=sum(item.cost_units for item in item_records),
            items=tuple(item_records),
        )
        return self._build_outcome(request, record, assets)

    def _invoke_provider(
        self,
        invocation: ProviderInvocation,
        cancellation: CancellationToken,
    ) -> ProviderAsset:
        result_queue: Queue[tuple[str, object]] = Queue(maxsize=1)

        def invoke() -> None:
            try:
                result_queue.put(("result", self._provider._generate(invocation, cancellation=cancellation)))
            except BaseException as exc:  # contained in a daemon boundary and re-sanitized by the caller
                result_queue.put(("error", exc))

        worker = Thread(target=invoke, name="image-panel-provider-attempt", daemon=True)
        worker.start()
        deadline = time.monotonic() + invocation.timeout_seconds
        while True:
            if cancellation.cancelled:
                raise ImagePanelError(
                    ImagePanelErrorCode.CANCELLED,
                    "Generation was cancelled",
                    category="state",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                cancellation.cancel()
                raise ImagePanelError(
                    ImagePanelErrorCode.PROVIDER_TIMEOUT,
                    "Provider attempt exceeded the configured timeout",
                    category="provider",
                )
            try:
                kind, value = result_queue.get(timeout=min(remaining, 0.01))
            except Empty:
                continue
            if kind == "result":
                if not isinstance(value, ProviderAsset):
                    raise TypeError("Adapter returned an invalid result type")
                return value
            if isinstance(value, Exception):
                raise value
            raise RuntimeError("Provider adapter raised a non-standard failure")

    def _build_outcome(
        self,
        request: GenerationRequest,
        record: GenerationRecord,
        assets: list[GeneratedAsset],
    ) -> GenerationOutcome:
        producer = ProducerIdentity("skill", SKILL_ID, SKILL_VERSION)
        input_contracts = [
            request.task_spec,
            request.task_context,
            request.product_context,
            request.approval_record,
            *request.input_asset_manifests,
            request.reference_manifest,
        ]
        source_contract_ids = tuple(str(item.contract_id) for item in input_contracts if item is not None)
        manifest_payload = {
            "manifest_id": f"asset-manifest:{request.request_id}",
            "manifest_revision": 1,
            "owner_type": "task",
            "owner_id": request.task_spec.payload["task_id"],
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "role": asset.role,
                    "media_type": "image",
                    "uri": asset.uri,
                    "sha256": asset.sha256,
                    "byte_size": asset.byte_size,
                    "provenance": {
                        "request_hash": request.request_hash,
                        "generation_record_id": record.record_id,
                    },
                    "created_at": record.completed_at,
                    "dimensions": {"width": asset.width, "height": asset.height},
                    "content_type": asset.content_type,
                    "derived_from": list(asset.derived_from),
                    "provider_metadata": {
                        "provider_id": record.provider_id,
                        "model_id": record.model_id,
                        "model_version": record.model_version,
                        "provider_asset_id": asset.provider_asset_id,
                        **dict(asset.provider_metadata),
                    },
                }
                for asset in assets
            ],
            "created_at": record.completed_at,
        }
        asset_manifest = build_envelope(
            contract_type="avp.contract.asset-manifest",
            payload=manifest_payload,
            producer=producer,
            correlation_id=request.task_spec.payload["task_id"],
            idempotency_key=f"{request.idempotency_key}:asset-manifest",
            task_id=request.task_spec.payload["task_id"],
            source_contract_ids=source_contract_ids,
            source_hashes=(request.request_hash,),
        )
        feedback_payload = {
            "feedback_id": f"feedback:{request.request_id}",
            "task_id": request.task_spec.payload["task_id"],
            "source_skill_id": SKILL_ID,
            "feedback_type": "generation_outcome",
            "statement": f"Image/panel generation ended with status {record.status.value}",
            "evidence_refs": [record.record_id, str(asset_manifest.contract_id)],
            "rule_scope": "product",
            "scope_key": {"product_id": request.product_id},
            "bindings": {
                "provider_id": record.provider_id,
                "model_id": record.model_id,
                "version": record.model_version,
            },
            "observed_at": record.completed_at,
            "submitted_by": SKILL_ID,
            "product_id": request.product_id,
            "asset_refs": [asset.asset_id for asset in assets],
            "severity": "info" if record.status is GenerationStatus.COMPLETED else "warning",
        }
        feedback_event = build_envelope(
            contract_type="avp.contract.feedback-event",
            payload=feedback_payload,
            producer=producer,
            correlation_id=request.task_spec.payload["task_id"],
            idempotency_key=f"{request.idempotency_key}:feedback-event",
            task_id=request.task_spec.payload["task_id"],
            source_contract_ids=(str(asset_manifest.contract_id),),
            source_hashes=(request.request_hash,),
        )
        event_type = {
            GenerationStatus.COMPLETED: "completed",
            GenerationStatus.PARTIAL_FAILURE: "failed",
            GenerationStatus.FAILED: "failed",
            GenerationStatus.CANCELLED: "cancelled",
        }[record.status]
        execution_payload = {
            "execution_id": f"execution:{request.request_id}",
            "task_id": request.task_spec.payload["task_id"],
            "skill_id": SKILL_ID,
            "event_type": event_type,
            "sequence": 1,
            "occurred_at": record.completed_at,
            "status": record.status.value,
            "input_contract_refs": list(source_contract_ids),
            "output_contract_refs": [str(asset_manifest.contract_id), str(feedback_event.contract_id)],
            "metrics": {
                "items": len(record.items),
                "attempts": record.total_attempts,
                "cost_units": record.total_cost_units,
            },
            "provider_binding": {
                "provider_id": record.provider_id,
                "model_id": record.model_id,
                "version": record.model_version,
            },
        }
        execution_event = build_envelope(
            contract_type="avp.contract.skill-execution-event",
            payload=execution_payload,
            producer=producer,
            correlation_id=request.task_spec.payload["task_id"],
            idempotency_key=f"{request.idempotency_key}:execution-event",
            task_id=request.task_spec.payload["task_id"],
            source_contract_ids=(str(asset_manifest.contract_id), str(feedback_event.contract_id)),
            source_hashes=(request.request_hash,),
        )
        validate_envelope(asset_manifest)
        validate_envelope(feedback_event)
        validate_envelope(execution_event)
        return GenerationOutcome(
            status=record.status,
            replayed=False,
            generation_record=record,
            asset_manifest=asset_manifest,
            feedback_event=feedback_event,
            execution_event=execution_event,
        )
