"""Foundation schema, semantic, publisher, and pollution validation."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .compatibility import Compatibility, SemVer, evaluate_compatibility
from .envelope import ContractEnvelope
from .errors import ContractError, ErrorCategory, ErrorCode
from .models import MODEL_REGISTRY
from .registry import FOUNDATION_VERSION, PRODUCER_AGENT_TYPES, get_contract_definition
from .serialization import content_digest, freeze_json


RULE_SCOPES = ("product", "sku", "category", "skill", "provider", "global")
REGISTERED_SKILL_IDS = {
    "product-knowledge",
    "reference-analysis",
    "storyboard",
    "product-image-panel-generation",
    "storyboard-master-video-planning",
    "video-generation",
    "qa-review",
}
NON_PRODUCT_KNOWLEDGE_SKILL_IDS = REGISTERED_SKILL_IDS - {"product-knowledge"}
_SCOPE_KEYS = {
    "product": ("product_id",),
    "sku": ("product_id", "sku_id"),
    "category": ("category_id",),
    "skill": ("skill_id",),
    "provider": ("provider_id",),
    "global": (),
}
_POLLUTED_STATUSES = {
    "pending",
    "pending_review",
    "conflict",
    "conflicting",
    "unconfirmed",
    "inferred",
    "awaiting_confirmation",
    "unapproved",
}
_POLLUTED_FIELD_TOKENS = {
    "pending",
    "conflict",
    "conflicting",
    "unresolved",
    "unconfirmed",
    "inferred",
    "unapproved",
    "review_context",
    "feedback_event",
}
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ValidatedContract:
    envelope: ContractEnvelope
    payload: Any


def _validation_error(message: str, *field_paths: str) -> ContractError:
    return ContractError(
        ErrorCode.CONTRACT_VALIDATION_FAILED,
        ErrorCategory.VALIDATION,
        message,
        field_paths=tuple(field_paths),
    )


def _matches_type(value: object, expected: str) -> bool:
    if expected == "array":
        return _is_array(value)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    return True


def _is_array(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _role_matches(
    role: str,
    producer_component_id: str,
    payload: Mapping[str, Any],
) -> bool:
    if role == producer_component_id:
        return True
    if role == "active-skill":
        return producer_component_id in REGISTERED_SKILL_IDS and payload.get("active_skill_id") == producer_component_id
    if role == "skill-runtime":
        return producer_component_id in REGISTERED_SKILL_IDS and payload.get("skill_id") == producer_component_id
    if role == "non-product-knowledge-skill":
        return producer_component_id in NON_PRODUCT_KNOWLEDGE_SKILL_IDS and payload.get("source_skill_id") == producer_component_id
    if role == "producing-skill":
        return producer_component_id in REGISTERED_SKILL_IDS and payload.get("owner_type") == "task"
    return False


def _validate_publisher(
    contract_type: str,
    producer_component_id: str | None,
    producer_agent: str | None,
    payload: Mapping[str, Any],
) -> None:
    if producer_component_id is None and producer_agent is None:
        return
    if producer_component_id is None or producer_agent is None:
        raise ContractError(
            ErrorCode.CONTRACT_PRODUCER_FORBIDDEN,
            ErrorCategory.AUTHORIZATION,
            "Publisher validation requires both producer agent and component identity",
            field_paths=("producer.agent", "producer.component_id"),
        )
    definition = get_contract_definition(contract_type)
    for role in definition.authorized_producers:
        if _role_matches(role, producer_component_id, payload):
            if producer_agent in PRODUCER_AGENT_TYPES[role]:
                return
            break
    if contract_type in {
        "avp.contract.product-context-bundle",
        "avp.contract.product-review-context",
        "avp.contract.rule-ref",
    }:
        raise ContractError(
            ErrorCode.PRODUCT_KNOWLEDGE_WRITE_FORBIDDEN,
            ErrorCategory.AUTHORIZATION,
            "Only Product Knowledge may publish this contract",
            field_paths=("producer.component_id",),
        )
    if contract_type == "avp.contract.approval-record":
        raise ContractError(
            ErrorCode.APPROVAL_AUTHORITY_INVALID,
            ErrorCategory.AUTHORIZATION,
            "Only the Authorized Approval Boundary may publish ApprovalRecord",
            field_paths=("producer.component_id",),
        )
    raise ContractError(
        ErrorCode.CONTRACT_PRODUCER_FORBIDDEN,
        ErrorCategory.AUTHORIZATION,
        "Producer is not authorized for this foundation contract",
        field_paths=("producer.component_id",),
    )


def _validate_rule_scope(payload: Mapping[str, Any]) -> None:
    scope = payload.get("rule_scope")
    if scope not in RULE_SCOPES:
        raise ContractError(
            ErrorCode.RULE_SCOPE_INVALID,
            ErrorCategory.VALIDATION,
            "rule_scope must be one of the six canonical scopes",
            field_paths=("payload.rule_scope",),
        )
    scope_key = payload.get("scope_key")
    if not isinstance(scope_key, Mapping):
        raise ContractError(
            ErrorCode.RULE_SCOPE_KEY_REQUIRED,
            ErrorCategory.VALIDATION,
            "scope_key must be an object",
            field_paths=("payload.scope_key",),
        )
    expected_keys = set(_SCOPE_KEYS[scope])
    actual_keys = set(scope_key)
    missing = [key for key in _SCOPE_KEYS[scope] if not scope_key.get(key)]
    unexpected = sorted(actual_keys - expected_keys)
    if missing or unexpected:
        raise ContractError(
            ErrorCode.RULE_SCOPE_KEY_REQUIRED,
            ErrorCategory.VALIDATION,
            "scope_key must contain exactly the canonical owner keys for its scope",
            field_paths=tuple(
                [*(f"payload.scope_key.{key}" for key in missing),
                 *(f"payload.scope_key.{key}" for key in unexpected)]
            ),
        )
    bindings = payload.get("bindings", {})
    if not isinstance(bindings, Mapping):
        raise _validation_error("bindings must be an object", "payload.bindings")
    if "provider_model" in bindings:
        raise ContractError(
            ErrorCode.RULE_BINDING_MISMATCH,
            ErrorCategory.VALIDATION,
            "provider_model is not a binding; use provider_id, model_id, and version",
            field_paths=("payload.bindings.provider_model",),
        )
    if scope == "provider" and isinstance(bindings, Mapping):
        owner_provider = scope_key.get("provider_id")
        runtime_provider = bindings.get("provider_id")
        if runtime_provider is not None and owner_provider != runtime_provider:
            raise ContractError(
                ErrorCode.RULE_BINDING_MISMATCH,
                ErrorCategory.CONFLICT,
                "Provider scope and runtime binding do not match",
                field_paths=("payload.scope_key.provider_id", "payload.bindings.provider_id"),
            )


def _parse_utc_timestamp(value: object, field_path: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _validation_error("effective period timestamps must use UTC Z form", field_path)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _validation_error("effective period timestamp is invalid", field_path) from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise _validation_error("effective period timestamps must use UTC", field_path)
    return parsed


def _validate_effective_period(payload: Mapping[str, Any]) -> None:
    period = payload.get("effective_period")
    if not isinstance(period, Mapping):
        raise _validation_error("effective_period must be an object", "payload.effective_period")
    parsed: dict[str, datetime] = {}
    for field_name in ("valid_from", "valid_until"):
        if field_name in period:
            parsed[field_name] = _parse_utc_timestamp(
                period[field_name],
                f"payload.effective_period.{field_name}",
            )
    if parsed.get("valid_from") and parsed.get("valid_until"):
        if parsed["valid_from"] >= parsed["valid_until"]:
            raise _validation_error(
                "valid_from must be earlier than valid_until",
                "payload.effective_period.valid_from",
                "payload.effective_period.valid_until",
            )


def _contains_pending_pollution(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            if any(token in normalized_key for token in _POLLUTED_FIELD_TOKENS):
                if nested not in (None, False, "", (), [], {}):
                    return True
            if key in {"status", "approval_state", "fact_state"} and isinstance(nested, str):
                if nested.lower() in _POLLUTED_STATUSES:
                    return True
            if key in {"pending", "unresolved_conflict", "unconfirmed"} and bool(nested):
                return True
            if _contains_pending_pollution(nested):
                return True
    elif _is_array(value):
        return any(_contains_pending_pollution(item) for item in value)
    return False


def _validate_product_context(payload: Mapping[str, Any]) -> None:
    if _contains_pending_pollution(payload):
        raise ContractError(
            ErrorCode.PRODUCT_CONTEXT_CONTAMINATED,
            ErrorCategory.VALIDATION,
            "ProductContextBundle contains pending, conflicting, or unconfirmed content",
            field_paths=("payload",),
        )
    for index, fact in enumerate(payload.get("facts", [])):
        if not isinstance(fact, Mapping):
            raise _validation_error("facts entries must be objects", f"payload.facts[{index}]")
        if fact.get("status", "confirmed") not in {"confirmed", "approved", "effective"}:
            raise ContractError(
                ErrorCode.PRODUCT_CONTEXT_CONTAMINATED,
                ErrorCategory.VALIDATION,
                "Product facts must be confirmed and effective",
                field_paths=(f"payload.facts[{index}].status",),
            )
        if "provenance" not in fact or fact["provenance"] in (None, "", (), [], {}):
            raise _validation_error(
                "product facts require provenance",
                f"payload.facts[{index}].provenance",
            )


def _validate_task_spec(payload: Mapping[str, Any]) -> None:
    for index, skill_id in enumerate(payload.get("requested_skills", [])):
        if not isinstance(skill_id, str) or skill_id not in REGISTERED_SKILL_IDS:
            raise _validation_error(
                "requested_skills must contain only registered public Skill IDs",
                f"payload.requested_skills[{index}]",
            )


def _validate_product_review_context(payload: Mapping[str, Any]) -> None:
    allowed_kinds = {
        "pending_feedback",
        "fact_conflict",
        "asset_confirmation",
        "inferred_fact",
        "identity_ambiguity",
    }
    for index, item in enumerate(payload.get("review_items", [])):
        if not isinstance(item, Mapping):
            raise _validation_error("review_items entries must be objects", f"payload.review_items[{index}]")
        required = ("review_item_id", "kind", "status", "candidate_values", "evidence_refs", "requested_decision")
        missing = [name for name in required if name not in item]
        if missing:
            raise _validation_error(
                "review item is missing required fields",
                *[f"payload.review_items[{index}].{name}" for name in missing],
            )
        if item["kind"] not in allowed_kinds:
            raise _validation_error("review item kind is unsupported", f"payload.review_items[{index}].kind")
        for field_name in ("candidate_values", "evidence_refs"):
            if not _is_array(item[field_name]):
                raise _validation_error(
                    f"review item {field_name} must be array",
                    f"payload.review_items[{index}].{field_name}",
                )
        if not isinstance(item["requested_decision"], str) or not item["requested_decision"]:
            raise _validation_error(
                "review item requested_decision must be a non-empty string",
                f"payload.review_items[{index}].requested_decision",
            )
        if item.get("status") in {"confirmed", "approved", "effective"}:
            raise ContractError(
                ErrorCode.PRODUCT_CONTEXT_CONTAMINATED,
                ErrorCategory.VALIDATION,
                "Confirmed or effective knowledge belongs in ProductContextBundle",
                field_paths=(f"payload.review_items[{index}].status",),
            )


def _validate_manifest_entries(contract_type: str, payload: Mapping[str, Any]) -> None:
    if contract_type == "avp.contract.asset-manifest":
        required = ("asset_id", "role", "media_type", "uri", "sha256", "byte_size", "provenance", "created_at")
        entries = payload.get("assets", [])
        path_prefix = "payload.assets"
    else:
        required = ("reference_id", "reference_type", "source_uri", "sha256", "usage", "provenance")
        entries = payload.get("references", [])
        path_prefix = "payload.references"
    for index, item in enumerate(entries):
        if not isinstance(item, Mapping):
            raise _validation_error("manifest entries must be objects", f"{path_prefix}[{index}]")
        missing = [name for name in required if name not in item]
        if missing:
            raise _validation_error(
                "manifest entry is missing required fields",
                *[f"{path_prefix}[{index}].{name}" for name in missing],
            )
        if not _SHA256_HEX.fullmatch(str(item["sha256"])):
            raise _validation_error(
                "manifest entry sha256 must be lowercase hexadecimal",
                f"{path_prefix}[{index}].sha256",
            )
        if contract_type == "avp.contract.asset-manifest":
            byte_size = item["byte_size"]
            if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
                raise _validation_error(
                    "asset byte_size must be a non-negative integer",
                    f"{path_prefix}[{index}].byte_size",
                )


def _validate_asset_manifest_publisher(
    payload: Mapping[str, Any],
    producer_component_id: str | None,
) -> None:
    if producer_component_id is None:
        return
    owner_type = payload.get("owner_type")
    if owner_type == "product" and producer_component_id != "product-knowledge":
        raise ContractError(
            ErrorCode.PRODUCT_KNOWLEDGE_WRITE_FORBIDDEN,
            ErrorCategory.AUTHORIZATION,
            "Only Product Knowledge may publish product-owned asset manifests",
            field_paths=("producer.component_id", "payload.owner_type"),
        )
    if owner_type == "task" and producer_component_id == "product-knowledge":
        raise ContractError(
            ErrorCode.CONTRACT_PRODUCER_FORBIDDEN,
            ErrorCategory.AUTHORIZATION,
            "Product Knowledge may publish product-owned asset manifests only",
            field_paths=("producer.component_id", "payload.owner_type"),
        )


def validate_payload(
    contract_type: str,
    payload: Mapping[str, Any],
    *,
    producer_component_id: str | None = None,
    producer_agent: str | None = None,
) -> Any:
    definition = get_contract_definition(contract_type)
    if not isinstance(payload, Mapping):
        raise _validation_error("payload must be an object", "payload")

    missing = [name for name in definition.required_fields if name not in payload]
    if missing:
        raise _validation_error(
            "payload is missing required fields",
            *[f"payload.{name}" for name in missing],
        )
    for field_name, expected_type in definition.field_types:
        if field_name in payload and not _matches_type(payload[field_name], expected_type):
            raise _validation_error(
                f"{field_name} must be {expected_type}",
                f"payload.{field_name}",
            )
    for field_name, allowed in definition.enum_fields:
        if payload[field_name] not in allowed:
            raise _validation_error(
                f"{field_name} contains an unsupported value",
                f"payload.{field_name}",
            )

    _validate_publisher(contract_type, producer_component_id, producer_agent, payload)
    if contract_type == "avp.contract.task-spec":
        _validate_task_spec(payload)
    if contract_type in {"avp.contract.feedback-event", "avp.contract.rule-ref"}:
        _validate_rule_scope(payload)
    if contract_type == "avp.contract.product-context-bundle":
        _validate_product_context(payload)
    if contract_type == "avp.contract.product-review-context":
        _validate_product_review_context(payload)
    if contract_type in {"avp.contract.asset-manifest", "avp.contract.reference-manifest"}:
        _validate_manifest_entries(contract_type, payload)
    if contract_type == "avp.contract.asset-manifest":
        _validate_asset_manifest_publisher(payload, producer_component_id)
    if contract_type == "avp.contract.rule-ref":
        _validate_effective_period(payload)
        if not _DIGEST.fullmatch(str(payload["content_digest"])):
            raise _validation_error("content_digest must be lowercase SHA-256", "payload.content_digest")

    model = MODEL_REGISTRY[contract_type]
    model_fields = {
        name: payload.get(name)
        for name in (*definition.required_fields, *definition.optional_fields)
    }
    typed_payload = model(**model_fields)
    object.__setattr__(typed_payload, "_contract_payload", freeze_json(payload))
    return typed_payload


def validate_envelope(envelope: ContractEnvelope, *, reader_version: str = FOUNDATION_VERSION) -> ValidatedContract:
    definition = get_contract_definition(envelope.contract_type)
    try:
        compatibility = evaluate_compatibility(reader_version, envelope.schema_version)
        writer_version = SemVer.parse(envelope.schema_version)
        registered_version = SemVer.parse(definition.version)
    except ValueError as exc:
        raise ContractError(
            ErrorCode.CONTRACT_SCHEMA_UNSUPPORTED,
            ErrorCategory.COMPATIBILITY,
            "Contract schema_version must be valid SemVer",
            field_paths=("schema_version",),
        ) from exc
    if compatibility is not Compatibility.COMPATIBLE:
        raise ContractError(
            ErrorCode.CONTRACT_SCHEMA_UNSUPPORTED,
            ErrorCategory.COMPATIBILITY,
            "Reader does not support the payload schema version",
            field_paths=("schema_version",),
        )
    if writer_version.major != registered_version.major:
        raise ContractError(
            ErrorCode.CONTRACT_SCHEMA_UNSUPPORTED,
            ErrorCategory.COMPATIBILITY,
            "Foundation Registry V1 supports only its registered schema major version",
            field_paths=("schema_version",),
        )
    if content_digest(envelope.payload) != envelope.payload_digest:
        raise _validation_error("payload_digest does not match canonical payload", "payload_digest")
    payload = validate_payload(
        envelope.contract_type,
        envelope.payload,
        producer_component_id=envelope.producer.component_id,
        producer_agent=envelope.producer.agent,
    )
    return ValidatedContract(envelope=envelope, payload=payload)
