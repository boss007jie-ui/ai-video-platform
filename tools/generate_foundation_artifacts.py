"""Deterministically generate Foundation Registry V1 schemas and fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
SEMVER_PATTERN = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.contracts.registry import (  # noqa: E402
    ENVELOPE_SCHEMA_ID,
    FOUNDATION_CONTRACT_IDS,
    FOUNDATION_REGISTRY_NAME,
    REGISTRY,
)
from ai_video_platform.contracts.serialization import content_digest  # noqa: E402


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _field_schema(expected_type: str | None) -> dict[str, Any]:
    if expected_type is None:
        return {}
    return {"type": expected_type}


def generate_schemas(output_root: Path = PROJECT_ROOT) -> None:
    schema_dir = output_root / "schemas" / "v1"
    envelope_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ENVELOPE_SCHEMA_ID,
        "title": "ContractEnvelope",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract_type",
            "schema_version",
            "contract_id",
            "created_at",
            "producer",
            "correlation_id",
            "idempotency_key",
            "payload_digest",
            "payload",
        ],
        "properties": {
            "contract_type": {"enum": list(FOUNDATION_CONTRACT_IDS)},
            "schema_version": {"type": "string", "pattern": SEMVER_PATTERN},
            "contract_id": {"type": "string", "format": "uuid"},
            "created_at": {"type": "string", "format": "date-time"},
            "producer": {
                "type": "object",
                "additionalProperties": False,
                "required": ["agent", "component_id", "component_version"],
                "properties": {
                    "agent": {"enum": ["hermes", "codex", "catpaw", "skill", "system", "human"]},
                    "component_id": {"type": "string", "minLength": 1},
                    "component_version": {"type": "string", "minLength": 1},
                },
            },
            "correlation_id": {"type": "string", "minLength": 1},
            "idempotency_key": {"type": "string", "minLength": 1},
            "payload_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            "payload": {"type": "object"},
            "task_id": {"type": "string"},
            "causation_id": {"type": "string"},
            "trace_id": {"type": "string"},
            "source_contract_ids": {"type": "array", "items": {"type": "string"}},
            "source_hashes": {"type": "array", "items": {"type": "string"}},
            "extensions": {"type": "object"},
        },
        "x-avp-registry": FOUNDATION_REGISTRY_NAME,
    }
    _write_json(schema_dir / "contract_envelope.schema.json", envelope_schema)

    for contract_type, definition in REGISTRY.items():
        field_types = dict(definition.field_types)
        enum_fields = dict(definition.enum_fields)
        properties: dict[str, Any] = {}
        for field_name in (*definition.required_fields, *definition.optional_fields):
            field_schema = _field_schema(field_types.get(field_name))
            if field_name in enum_fields:
                field_schema["enum"] = list(enum_fields[field_name])
            properties[field_name] = field_schema
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": contract_type,
            "title": definition.name,
            "type": "object",
            "additionalProperties": True,
            "required": list(definition.required_fields),
            "properties": properties,
            "x-avp-registry": FOUNDATION_REGISTRY_NAME,
            "x-avp-version": definition.version,
            "x-avp-authorized-producers": list(definition.authorized_producers),
            "x-avp-authorized-consumers": list(definition.authorized_consumers),
        }
        _write_json(schema_dir / definition.schema_filename, schema)


def _payloads() -> dict[str, dict[str, Any]]:
    sha_zero = "sha256:" + "0" * 64
    return {
        "avp.contract.task-spec": {
            "task_id": "task-synthetic-001",
            "task_type": "single-skill",
            "requested_skills": ["storyboard"],
            "objective": "Produce a synthetic contract fixture",
            "input_refs": [],
            "requested_outputs": ["synthetic-output"],
            "created_by": "human:test",
            "created_at": "2026-07-20T00:00:00Z",
        },
        "avp.contract.task-context": {
            "task_id": "task-synthetic-001",
            "context_revision": 1,
            "task_spec_ref": "contract-synthetic-task-spec",
            "active_skill_id": "storyboard",
            "input_contract_refs": [],
            "bindings": {},
            "state": "ready",
            "updated_at": "2026-07-20T00:00:00Z",
        },
        "avp.contract.skill-execution-event": {
            "execution_id": "execution-synthetic-001",
            "task_id": "task-synthetic-001",
            "skill_id": "storyboard",
            "event_type": "accepted",
            "sequence": 1,
            "occurred_at": "2026-07-20T00:00:00Z",
            "status": "accepted",
            "input_contract_refs": [],
        },
        "avp.contract.product-context-bundle": {
            "bundle_id": "bundle-synthetic-001",
            "bundle_revision": 1,
            "product_id": "product-synthetic-001",
            "purpose": "storyboard",
            "facts": [],
            "approved_asset_refs": [],
            "rule_refs": [],
            "known_error_refs": [],
            "successful_pattern_refs": [],
            "source_evidence": [],
            "generated_at": "2026-07-20T00:00:00Z",
        },
        "avp.contract.product-review-context": {
            "review_context_id": "review-context-synthetic-001",
            "context_revision": 1,
            "product_id": "product-synthetic-001",
            "review_items": [],
            "generated_at": "2026-07-20T00:00:00Z",
        },
        "avp.contract.feedback-event": {
            "feedback_id": "feedback-synthetic-001",
            "task_id": "task-synthetic-001",
            "source_skill_id": "storyboard",
            "feedback_type": "observation",
            "statement": "Synthetic observation only",
            "evidence_refs": ["evidence-synthetic-001"],
            "rule_scope": "product",
            "scope_key": {"product_id": "product-synthetic-001"},
            "bindings": {},
            "observed_at": "2026-07-20T00:00:00Z",
            "submitted_by": "skill:storyboard",
        },
        "avp.contract.rule-ref": {
            "rule_id": "rule-synthetic-001",
            "rule_version": "1.0.0",
            "rule_scope": "product",
            "scope_key": {"product_id": "product-synthetic-001"},
            "bindings": {},
            "status": "approved",
            "effective_period": {},
            "content_digest": sha_zero,
        },
        "avp.contract.asset-manifest": {
            "manifest_id": "asset-manifest-synthetic-001",
            "manifest_revision": 1,
            "owner_type": "task",
            "owner_id": "task-synthetic-001",
            "assets": [],
            "created_at": "2026-07-20T00:00:00Z",
        },
        "avp.contract.reference-manifest": {
            "reference_manifest_id": "reference-manifest-synthetic-001",
            "revision": 1,
            "task_id": "task-synthetic-001",
            "references": [],
            "created_at": "2026-07-20T00:00:00Z",
        },
        "avp.contract.review-decision": {
            "review_decision_id": "review-decision-synthetic-001",
            "subject_ref": {"contract_id": "subject-synthetic-001", "digest": sha_zero},
            "decision": "defer",
            "decided_by": "qa-review:synthetic",
            "decided_at": "2026-07-20T00:00:00Z",
            "criteria_results": [],
            "evidence_refs": [],
        },
        "avp.contract.approval-record": {
            "approval_id": "approval-synthetic-001",
            "subject_ref": {"contract_id": "subject-synthetic-001", "digest": sha_zero},
            "approval_type": "release",
            "outcome": "denied",
            "authority": {"authority_id": "approval-boundary-synthetic"},
            "decided_at": "2026-07-20T00:00:00Z",
            "decision_ref": "review-decision-synthetic-001",
        },
    }


def _producer_for(contract_type: str) -> tuple[str, str]:
    return {
        "avp.contract.task-spec": ("authorized-direct-cli-caller", "human"),
        "avp.contract.task-context": ("hermes", "hermes"),
        "avp.contract.skill-execution-event": ("storyboard", "skill"),
        "avp.contract.product-context-bundle": ("product-knowledge", "skill"),
        "avp.contract.product-review-context": ("product-knowledge", "skill"),
        "avp.contract.feedback-event": ("storyboard", "skill"),
        "avp.contract.rule-ref": ("product-knowledge", "skill"),
        "avp.contract.asset-manifest": ("storyboard", "skill"),
        "avp.contract.reference-manifest": ("reference-analysis", "skill"),
        "avp.contract.review-decision": ("qa-review", "skill"),
        "avp.contract.approval-record": ("authorized-approval-boundary", "system"),
    }[contract_type]


def generate_fixtures(output_root: Path = PROJECT_ROOT) -> None:
    fixture_root = output_root / "fixtures" / "contracts"
    for contract_type, payload in _payloads().items():
        definition = REGISTRY[contract_type]
        slug = contract_type.removeprefix("avp.contract.")
        producer, producer_agent = _producer_for(contract_type)
        base_manifest = {
            "contract_type": contract_type,
            "schema_version": definition.version,
            "producer_component_id": producer,
            "producer_agent": producer_agent,
            "synthetic": True,
            "contains_real_data": False,
            "contains_secrets": False,
        }
        variants = {
            "minimal-valid": (payload, "valid", None),
            "full-valid": ({**payload, "extensions": {"fixture_note": "synthetic-full"}}, "valid", None),
            "invalid": ({key: value for index, (key, value) in enumerate(payload.items()) if index != 0}, "invalid", "CONTRACT_VALIDATION_FAILED"),
            "compatibility": (payload, "valid", None),
            "replay": (payload, "valid", None),
        }
        for fixture_kind, (fixture_payload, expected_result, expected_error) in variants.items():
            manifest = {
                **base_manifest,
                "fixture_id": f"{slug}-{fixture_kind}-v1",
                "fixture_kind": fixture_kind,
                "purpose": f"Foundation Registry V1 {fixture_kind} fixture",
                "expected_result": expected_result,
                "expected_error": expected_error,
                "retryable": False,
                "payload_digest": content_digest(fixture_payload),
            }
            _write_json(
                fixture_root / slug / f"{fixture_kind}.json",
                {"manifest": manifest, "payload": fixture_payload},
            )


def main() -> None:
    generate_schemas()
    generate_fixtures()


if __name__ == "__main__":
    main()
