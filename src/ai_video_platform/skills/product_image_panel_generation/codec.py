"""Bounded JSON projections for the Skill-local public interface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from ai_video_platform.contracts import ContractEnvelope, ProducerIdentity

from .errors import ImagePanelError, ImagePanelErrorCode
from .models import GenerationBudget, GenerationCommand, GenerationItem, GenerationRequest, ModelProfile


def _contract_from_mapping(value: object, field_path: str) -> ContractEnvelope:
    if not isinstance(value, Mapping):
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "Embedded foundation contract must be an object",
            field_paths=(field_path,),
        )
    try:
        producer = value["producer"]
        if not isinstance(producer, Mapping):
            raise TypeError("producer")
        created_at_text = str(value["created_at"])
        if not created_at_text.endswith("Z"):
            raise ValueError("created_at")
        created_at = datetime.fromisoformat(created_at_text[:-1] + "+00:00")
        return ContractEnvelope(
            contract_type=str(value["contract_type"]),
            schema_version=str(value["schema_version"]),
            contract_id=UUID(str(value["contract_id"])),
            created_at=created_at,
            producer=ProducerIdentity(
                str(producer["agent"]),
                str(producer["component_id"]),
                str(producer["component_version"]),
            ),
            correlation_id=str(value["correlation_id"]),
            idempotency_key=str(value["idempotency_key"]),
            payload_digest=str(value["payload_digest"]),
            payload=value["payload"],
            task_id=str(value["task_id"]) if value.get("task_id") is not None else None,
            causation_id=str(value["causation_id"]) if value.get("causation_id") is not None else None,
            trace_id=str(value["trace_id"]) if value.get("trace_id") is not None else None,
            source_contract_ids=tuple(str(item) for item in value.get("source_contract_ids", ())),
            source_hashes=tuple(str(item) for item in value.get("source_hashes", ())),
            extensions=value.get("extensions", {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "Embedded foundation contract is malformed",
            field_paths=(field_path,),
            details={"cause_type": type(exc).__name__},
        ) from exc


def _optional_contract(value: object, field_path: str) -> ContractEnvelope | None:
    return None if value is None else _contract_from_mapping(value, field_path)


def generation_request_from_mapping(value: object) -> GenerationRequest:
    if not isinstance(value, Mapping):
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "request must be an object",
            field_paths=("request",),
        )
    try:
        budget_value = value.get("budget")
        budget = None
        if budget_value is not None:
            if not isinstance(budget_value, Mapping):
                raise TypeError("budget")
            budget = GenerationBudget(
                currency=str(budget_value["currency"]),
                max_cost_units=int(budget_value["max_cost_units"]),
                max_attempts=int(budget_value["max_attempts"]),
                timeout_seconds=float(budget_value["timeout_seconds"]),
                max_concurrency=int(budget_value["max_concurrency"]),
            )
        items_value = value["items"]
        if not isinstance(items_value, list):
            raise TypeError("items")
        items = tuple(
            GenerationItem(
                item_id=str(item["item_id"]),
                role=str(item["role"]),
                prompt=str(item["prompt"]),
                width=int(item["width"]),
                height=int(item["height"]),
                input_asset_ids=tuple(str(asset_id) for asset_id in item.get("input_asset_ids", ())),
            )
            for item in items_value
            if isinstance(item, Mapping)
        )
        if len(items) != len(items_value):
            raise TypeError("items")
        manifests_value = value.get("input_asset_manifests", [])
        if not isinstance(manifests_value, list):
            raise TypeError("input_asset_manifests")
        return GenerationRequest(
            command=GenerationCommand(str(value["command"])),
            request_id=str(value["request_id"]),
            idempotency_key=str(value["idempotency_key"]),
            request_hash=str(value["request_hash"]),
            task_spec=_contract_from_mapping(value["task_spec"], "request.task_spec"),
            task_context=_contract_from_mapping(value["task_context"], "request.task_context"),
            product_context=_optional_contract(value.get("product_context"), "request.product_context"),
            approval_record=_optional_contract(value.get("approval_record"), "request.approval_record"),
            input_asset_manifests=tuple(
                _contract_from_mapping(item, f"request.input_asset_manifests[{index}]")
                for index, item in enumerate(manifests_value)
            ),
            reference_manifest=_optional_contract(value.get("reference_manifest"), "request.reference_manifest"),
            product_id=str(value["product_id"]),
            sku_id=str(value["sku_id"]) if value.get("sku_id") is not None else None,
            expected_context_revision=int(value["expected_context_revision"]),
            items=items,
            model_profile_id=str(value["model_profile_id"]),
            model_profile_digest=str(value["model_profile_digest"]),
            budget=budget,
        )
    except ImagePanelError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "Generation request is malformed",
            field_paths=("request",),
            details={"cause_type": type(exc).__name__},
        ) from exc


def generation_request_to_mapping(request: GenerationRequest) -> dict[str, Any]:
    return {
        "command": request.command.value,
        "request_id": request.request_id,
        "idempotency_key": request.idempotency_key,
        "request_hash": request.request_hash,
        "task_spec": request.task_spec.to_dict(),
        "task_context": request.task_context.to_dict(),
        "product_context": request.product_context.to_dict() if request.product_context else None,
        "approval_record": request.approval_record.to_dict() if request.approval_record else None,
        "input_asset_manifests": [item.to_dict() for item in request.input_asset_manifests],
        "reference_manifest": request.reference_manifest.to_dict() if request.reference_manifest else None,
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


def model_profile_from_mapping(value: object) -> ModelProfile:
    if not isinstance(value, Mapping):
        raise ImagePanelError(
            ImagePanelErrorCode.MODEL_PROFILE_INVALID,
            "model_profile must be an object",
            field_paths=("model_profile",),
        )
    try:
        return ModelProfile(
            profile_id=str(value["profile_id"]),
            provider_id=str(value["provider_id"]),
            model_id=str(value["model_id"]),
            version=str(value["version"]),
            cost_per_attempt=int(value["cost_per_attempt"]),
            min_dimension=int(value["min_dimension"]),
            max_dimension=int(value["max_dimension"]),
            dimension_multiple=int(value["dimension_multiple"]),
            max_concurrency=int(value["max_concurrency"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.MODEL_PROFILE_INVALID,
            "model_profile is malformed",
            field_paths=("model_profile",),
            details={"cause_type": type(exc).__name__},
        ) from exc


def model_profile_to_mapping(profile: ModelProfile) -> dict[str, Any]:
    return {
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
