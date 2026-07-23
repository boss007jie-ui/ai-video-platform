"""Immutable public request models and canonical request hashing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Event
from types import MappingProxyType
from typing import Any, Mapping

from ai_video_platform.contracts import ContractEnvelope
from ai_video_platform.contracts.serialization import content_digest

from .product_data import ProductFacts


class GenerationCommand(str, Enum):
    GENERATE_PRODUCT_IMAGE = "generate-product-image"
    GENERATE_PANEL = "generate-panel"
    INSPECT_GENERATION_REQUEST = "inspect-generation-request"


class GenerationStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class GenerationItem:
    item_id: str
    role: str
    prompt: str
    width: int
    height: int
    input_asset_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GenerationBudget:
    currency: str
    max_cost_units: int
    max_attempts: int
    timeout_seconds: float
    max_concurrency: int


@dataclass(frozen=True, slots=True)
class ModelProfile:
    profile_id: str
    provider_id: str
    model_id: str
    version: str
    cost_per_attempt: int
    min_dimension: int
    max_dimension: int
    dimension_multiple: int
    max_concurrency: int


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    command: GenerationCommand
    request_id: str
    idempotency_key: str
    request_hash: str
    task_spec: ContractEnvelope
    task_context: ContractEnvelope
    product_context: ContractEnvelope | None
    approval_record: ContractEnvelope | None
    input_asset_manifests: tuple[ContractEnvelope, ...]
    reference_manifest: ContractEnvelope | None
    product_id: str
    sku_id: str | None
    expected_context_revision: int
    items: tuple[GenerationItem, ...]
    model_profile_id: str
    model_profile_digest: str
    budget: GenerationBudget | None


@dataclass(frozen=True, slots=True)
class PreflightInspection:
    approved: bool
    request_hash: str
    estimated_max_cost_units: int
    item_count: int
    profile_id: str
    product_facts: ProductFacts


class CancellationToken:
    """Thread-safe cooperative cancellation signal for Provider seams."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class GeneratedAsset:
    asset_id: str
    item_id: str
    role: str
    uri: str
    content_type: str
    sha256: str
    byte_size: int
    width: int
    height: int
    derived_from: tuple[str, ...]
    provider_asset_id: str
    provider_metadata: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class ItemGenerationRecord:
    item_id: str
    status: ItemStatus
    attempts: int
    cost_units: int
    asset_id: str | None = None
    error: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    record_id: str
    request_id: str
    request_hash: str
    status: GenerationStatus
    product_id: str
    profile_id: str
    provider_id: str
    model_id: str
    model_version: str
    started_at: str
    completed_at: str
    total_attempts: int
    total_cost_units: int
    items: tuple[ItemGenerationRecord, ...]


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    status: GenerationStatus
    replayed: bool
    generation_record: GenerationRecord
    asset_manifest: ContractEnvelope
    feedback_event: ContractEnvelope
    execution_event: ContractEnvelope


def _contract_ref(envelope: ContractEnvelope | None) -> dict[str, str] | None:
    if envelope is None:
        return None
    return {
        "contract_id": str(envelope.contract_id),
        "contract_type": envelope.contract_type,
        "payload_digest": envelope.payload_digest,
        "schema_version": envelope.schema_version,
    }


def calculate_request_hash(request: GenerationRequest) -> str:
    """Hash every execution-affecting input except approval and the hash itself."""

    payload = {
        "command": request.command.value,
        "request_id": request.request_id,
        "idempotency_key": request.idempotency_key,
        "task_spec": _contract_ref(request.task_spec),
        "task_context": _contract_ref(request.task_context),
        "product_context": _contract_ref(request.product_context),
        "input_asset_manifests": [_contract_ref(item) for item in request.input_asset_manifests],
        "reference_manifest": _contract_ref(request.reference_manifest),
        "product_id": request.product_id,
        "sku_id": request.sku_id,
        "expected_context_revision": request.expected_context_revision,
        "items": [
            {
                "item_id": item.item_id,
                "role": item.role,
                "prompt": item.prompt,
                "width": item.width,
                "height": item.height,
                "input_asset_ids": list(item.input_asset_ids),
            }
            for item in request.items
        ],
        "model_profile_id": request.model_profile_id,
        "model_profile_digest": request.model_profile_digest,
        "budget": None
        if request.budget is None
        else {
            "currency": request.budget.currency,
            "max_cost_units": request.budget.max_cost_units,
            "max_attempts": request.budget.max_attempts,
            "timeout_seconds": request.budget.timeout_seconds,
            "max_concurrency": request.budget.max_concurrency,
        },
    }
    return content_digest(payload)


def calculate_model_profile_digest(profile: ModelProfile) -> str:
    return content_digest(
        {
            "profile_id": profile.profile_id,
            "provider_id": profile.provider_id,
            "model_id": profile.model_id,
            "version": profile.version,
            "cost_per_attempt": profile.cost_per_attempt,
            "min_dimension": profile.min_dimension,
            "max_dimension": profile.max_dimension,
            "dimension_multiple": profile.dimension_multiple,
            "max_concurrency": profile.max_concurrency,
        }
    )
