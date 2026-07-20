from __future__ import annotations

import unittest
from dataclasses import fields
from datetime import datetime, timezone

from ai_video_platform.contracts.envelope import ProducerIdentity, build_envelope
from ai_video_platform.contracts.errors import ContractError, ErrorCode
from ai_video_platform.contracts.models import MODEL_REGISTRY
from ai_video_platform.contracts.registry import FOUNDATION_CONTRACT_IDS, REGISTRY
from ai_video_platform.contracts.validation import validate_envelope, validate_payload
from ai_video_platform.core.ids import uuid7


def _task_spec() -> dict[str, object]:
    return {
        "task_id": "task-001",
        "task_type": "single-skill",
        "requested_skills": ["storyboard"],
        "objective": "Create a synthetic plan",
        "input_refs": [],
        "requested_outputs": ["synthetic-output"],
        "created_by": "human:test",
        "created_at": "2026-07-20T00:00:00Z",
    }


class ValidationAndPermissionTests(unittest.TestCase):
    def test_model_registry_is_mechanically_aligned_with_identity_registry(self) -> None:
        self.assertEqual(tuple(MODEL_REGISTRY), FOUNDATION_CONTRACT_IDS)
        for contract_type, model in MODEL_REGISTRY.items():
            model_field_names = tuple(field.name for field in fields(model))
            definition = REGISTRY[contract_type]
            self.assertEqual(
                model_field_names,
                (*definition.required_fields, *definition.optional_fields),
            )

    def test_registered_skill_runtime_is_authorized_by_actual_skill_id(self) -> None:
        payload = {
            "execution_id": "execution-001",
            "task_id": "task-001",
            "skill_id": "storyboard",
            "event_type": "started",
            "sequence": 1,
            "occurred_at": "2026-07-20T00:00:00Z",
            "status": "running",
            "input_contract_refs": [],
        }

        result = validate_payload(
            "avp.contract.skill-execution-event",
            payload,
            producer_component_id="storyboard",
            producer_agent="skill",
        )

        self.assertEqual(result.skill_id, "storyboard")

    def test_task_spec_rejects_unregistered_public_skill_id(self) -> None:
        payload = _task_spec()
        payload["requested_skills"] = ["storyboard", "unregistered-skill"]

        with self.assertRaises(ContractError) as captured:
            validate_payload("avp.contract.task-spec", payload)

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)
        self.assertEqual(captured.exception.field_paths, ("payload.requested_skills[1]",))

    def test_product_knowledge_cannot_reemit_feedback_event(self) -> None:
        payload = {
            "feedback_id": "feedback-001",
            "task_id": "task-001",
            "source_skill_id": "product-knowledge",
            "feedback_type": "normalization",
            "statement": "Synthetic statement",
            "evidence_refs": ["evidence-001"],
            "rule_scope": "product",
            "scope_key": {"product_id": "product-001"},
            "bindings": {},
            "observed_at": "2026-07-20T00:00:00Z",
            "submitted_by": "skill:product-knowledge",
        }

        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.feedback-event",
                payload,
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_PRODUCER_FORBIDDEN)

    def test_valid_envelope_returns_typed_payload_model(self) -> None:
        envelope = build_envelope(
            contract_type="avp.contract.task-spec",
            payload=_task_spec(),
            producer=ProducerIdentity("human", "authorized-direct-cli-caller", "1.0.0"),
            correlation_id="corr-001",
            idempotency_key="idem-001",
            contract_id=uuid7(timestamp_ms=1_700_000_000_000, random_bits=2),
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        result = validate_envelope(envelope)

        self.assertEqual(type(result.payload).__name__, "TaskSpec")
        self.assertEqual(result.payload.task_id, "task-001")

    def test_missing_required_field_uses_stable_error_model(self) -> None:
        payload = _task_spec()
        del payload["objective"]

        with self.assertRaises(ContractError) as captured:
            validate_payload("avp.contract.task-spec", payload)

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)
        self.assertEqual(captured.exception.field_paths, ("payload.objective",))
        self.assertFalse(captured.exception.retryable)

    def test_product_context_rejects_non_product_knowledge_publisher(self) -> None:
        payload = {
            "bundle_id": "bundle-001",
            "bundle_revision": 1,
            "product_id": "product-001",
            "purpose": "storyboard",
            "facts": [],
            "approved_asset_refs": [],
            "rule_refs": [],
            "known_error_refs": [],
            "successful_pattern_refs": [],
            "source_evidence": [],
            "generated_at": "2026-07-20T00:00:00Z",
        }

        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.product-context-bundle",
                payload,
                producer_component_id="storyboard",
                producer_agent="skill",
            )

        self.assertEqual(captured.exception.code, ErrorCode.PRODUCT_KNOWLEDGE_WRITE_FORBIDDEN)

    def test_product_context_rejects_pending_or_unconfirmed_content(self) -> None:
        payload = {
            "bundle_id": "bundle-001",
            "bundle_revision": 1,
            "product_id": "product-001",
            "purpose": "storyboard",
            "facts": [{"fact_id": "fact-001", "status": "pending", "value": "red"}],
            "approved_asset_refs": [],
            "rule_refs": [],
            "known_error_refs": [],
            "successful_pattern_refs": [],
            "source_evidence": ["evidence-001"],
            "generated_at": "2026-07-20T00:00:00Z",
        }

        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.product-context-bundle",
                payload,
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )

        self.assertEqual(captured.exception.code, ErrorCode.PRODUCT_CONTEXT_CONTAMINATED)

    def test_product_context_requires_fact_provenance(self) -> None:
        payload = {
            "bundle_id": "bundle-001",
            "bundle_revision": 1,
            "product_id": "product-001",
            "purpose": "storyboard",
            "facts": [{"fact_id": "fact-001", "status": "confirmed", "value": "red"}],
            "approved_asset_refs": [],
            "rule_refs": [],
            "known_error_refs": [],
            "successful_pattern_refs": [],
            "source_evidence": ["evidence-001"],
            "generated_at": "2026-07-20T00:00:00Z",
        }

        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.product-context-bundle",
                payload,
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)
        self.assertEqual(captured.exception.field_paths, ("payload.facts[0].provenance",))

    def test_qa_review_cannot_publish_approval_record(self) -> None:
        payload = {
            "approval_id": "approval-001",
            "subject_ref": {"contract_id": "subject-001", "digest": "sha256:" + "0" * 64},
            "approval_type": "release",
            "outcome": "approved",
            "authority": {"authority_id": "qa-review"},
            "decided_at": "2026-07-20T00:00:00Z",
            "decision_ref": "decision-001",
        }

        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.approval-record",
                payload,
                producer_component_id="qa-review",
                producer_agent="skill",
            )

        self.assertEqual(captured.exception.code, ErrorCode.APPROVAL_AUTHORITY_INVALID)

    def test_only_product_knowledge_can_publish_product_asset_manifest(self) -> None:
        payload = {
            "manifest_id": "asset-manifest-001",
            "manifest_revision": 1,
            "owner_type": "product",
            "owner_id": "product-001",
            "assets": [],
            "created_at": "2026-07-20T00:00:00Z",
        }

        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.asset-manifest",
                payload,
                producer_component_id="hermes",
                producer_agent="hermes",
            )

        self.assertEqual(captured.exception.code, ErrorCode.PRODUCT_KNOWLEDGE_WRITE_FORBIDDEN)

        result = validate_payload(
            "avp.contract.asset-manifest",
            payload,
            producer_component_id="product-knowledge",
            producer_agent="skill",
        )
        self.assertEqual(result.owner_type, "product")

    def test_rule_scope_is_exactly_one_of_six_and_provider_is_disambiguated(self) -> None:
        base = {
            "rule_id": "rule-001",
            "rule_version": "1.0.0",
            "rule_scope": "provider",
            "scope_key": {"provider_id": "provider-a"},
            "bindings": {"provider_id": "provider-a", "model_id": "model-a"},
            "status": "approved",
            "effective_period": {},
            "content_digest": "sha256:" + "1" * 64,
        }
        validated = validate_payload(
            "avp.contract.rule-ref",
            base,
            producer_component_id="product-knowledge",
            producer_agent="skill",
        )
        self.assertEqual(validated.rule_scope, "provider")

        invalid_scope = dict(base, rule_scope="provider_model")
        with self.assertRaises(ContractError) as captured_scope:
            validate_payload(
                "avp.contract.rule-ref",
                invalid_scope,
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )
        self.assertEqual(captured_scope.exception.code, ErrorCode.RULE_SCOPE_INVALID)

        mismatch = dict(base, bindings={"provider_id": "provider-b"})
        with self.assertRaises(ContractError) as captured_mismatch:
            validate_payload(
                "avp.contract.rule-ref",
                mismatch,
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )
        self.assertEqual(captured_mismatch.exception.code, ErrorCode.RULE_BINDING_MISMATCH)

    def test_rule_effective_period_requires_ordered_utc_timestamps(self) -> None:
        base = {
            "rule_id": "rule-001",
            "rule_version": "1.0.0",
            "rule_scope": "product",
            "scope_key": {"product_id": "product-001"},
            "bindings": {},
            "status": "approved",
            "effective_period": {
                "valid_from": "2026-07-20T00:00:00Z",
                "valid_until": "2026-07-21T00:00:00Z",
            },
            "content_digest": "sha256:" + "1" * 64,
        }

        result = validate_payload(
            "avp.contract.rule-ref",
            base,
            producer_component_id="product-knowledge",
            producer_agent="skill",
        )
        self.assertEqual(result.effective_period["valid_until"], "2026-07-21T00:00:00Z")

        reversed_period = {
            **base,
            "effective_period": {
                "valid_from": "2026-07-21T00:00:00Z",
                "valid_until": "2026-07-20T00:00:00Z",
            },
        }
        with self.assertRaises(ContractError) as captured_order:
            validate_payload(
                "avp.contract.rule-ref",
                reversed_period,
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )
        self.assertEqual(captured_order.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)
        self.assertEqual(
            captured_order.exception.field_paths,
            ("payload.effective_period.valid_from", "payload.effective_period.valid_until"),
        )

        non_utc_period = {
            **base,
            "effective_period": {"valid_from": "2026-07-20T08:00:00+08:00"},
        }
        with self.assertRaises(ContractError) as captured_utc:
            validate_payload(
                "avp.contract.rule-ref",
                non_utc_period,
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )
        self.assertEqual(captured_utc.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)
        self.assertEqual(
            captured_utc.exception.field_paths,
            ("payload.effective_period.valid_from",),
        )

    def test_product_review_context_validates_nested_review_items(self) -> None:
        payload = {
            "review_context_id": "review-context-001",
            "context_revision": 1,
            "product_id": "product-001",
            "review_items": [
                {
                    "review_item_id": "review-item-001",
                    "kind": "fact_conflict",
                    "status": "pending_review",
                    "candidate_values": ["red", "blue"],
                    "evidence_refs": ["evidence-001"],
                    "requested_decision": "Select the confirmed color",
                }
            ],
            "generated_at": "2026-07-20T00:00:00Z",
        }

        result = validate_payload(
            "avp.contract.product-review-context",
            payload,
            producer_component_id="product-knowledge",
            producer_agent="skill",
        )
        self.assertEqual(result.review_items[0]["kind"], "fact_conflict")

        invalid = {**payload, "review_items": [{**payload["review_items"][0], "candidate_values": "red"}]}
        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.product-review-context",
                invalid,
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )
        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)
        self.assertEqual(captured.exception.field_paths, ("payload.review_items[0].candidate_values",))

    def test_asset_and_reference_manifests_validate_nested_entries(self) -> None:
        sha = "0" * 64
        asset_payload = {
            "manifest_id": "asset-manifest-001",
            "manifest_revision": 1,
            "owner_type": "task",
            "owner_id": "task-001",
            "assets": [
                {
                    "asset_id": "asset-001",
                    "role": "synthetic-test",
                    "media_type": "image/png",
                    "uri": "file:///synthetic/asset.png",
                    "sha256": sha,
                    "byte_size": 128,
                    "provenance": {"kind": "synthetic"},
                    "created_at": "2026-07-20T00:00:00Z",
                }
            ],
            "created_at": "2026-07-20T00:00:00Z",
        }
        asset_result = validate_payload(
            "avp.contract.asset-manifest",
            asset_payload,
            producer_component_id="storyboard",
            producer_agent="skill",
        )
        self.assertEqual(asset_result.assets[0]["sha256"], sha)

        bad_asset = {**asset_payload, "assets": [{**asset_payload["assets"][0], "byte_size": -1}]}
        with self.assertRaises(ContractError) as captured_asset:
            validate_payload(
                "avp.contract.asset-manifest",
                bad_asset,
                producer_component_id="storyboard",
                producer_agent="skill",
            )
        self.assertEqual(captured_asset.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)

        reference_payload = {
            "reference_manifest_id": "reference-manifest-001",
            "revision": 1,
            "task_id": "task-001",
            "references": [
                {
                    "reference_id": "reference-001",
                    "reference_type": "synthetic-image",
                    "source_uri": "file:///synthetic/reference.png",
                    "sha256": sha,
                    "usage": "composition-only",
                    "provenance": {"kind": "synthetic"},
                }
            ],
            "created_at": "2026-07-20T00:00:00Z",
        }
        reference_result = validate_payload(
            "avp.contract.reference-manifest",
            reference_payload,
            producer_component_id="reference-analysis",
            producer_agent="skill",
        )
        self.assertEqual(reference_result.references[0]["reference_id"], "reference-001")

        bad_reference = {
            **reference_payload,
            "references": [{**reference_payload["references"][0], "sha256": "not-a-hash"}],
        }
        with self.assertRaises(ContractError) as captured_reference:
            validate_payload(
                "avp.contract.reference-manifest",
                bad_reference,
                producer_component_id="reference-analysis",
                producer_agent="skill",
            )
        self.assertEqual(captured_reference.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)

    def test_valid_component_name_cannot_be_spoofed_by_wrong_agent(self) -> None:
        payload = {
            "bundle_id": "bundle-001",
            "bundle_revision": 1,
            "product_id": "product-001",
            "purpose": "storyboard",
            "facts": [],
            "approved_asset_refs": [],
            "rule_refs": [],
            "known_error_refs": [],
            "successful_pattern_refs": [],
            "source_evidence": [],
            "generated_at": "2026-07-20T00:00:00Z",
        }

        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.product-context-bundle",
                payload,
                producer_component_id="product-knowledge",
                producer_agent="hermes",
            )

        self.assertEqual(captured.exception.code, ErrorCode.PRODUCT_KNOWLEDGE_WRITE_FORBIDDEN)

    def test_product_context_rejects_pending_content_hidden_in_unknown_field(self) -> None:
        payload = {
            "bundle_id": "bundle-001",
            "bundle_revision": 1,
            "product_id": "product-001",
            "purpose": "storyboard",
            "facts": [],
            "approved_asset_refs": [],
            "rule_refs": [],
            "known_error_refs": [],
            "successful_pattern_refs": [],
            "source_evidence": [],
            "generated_at": "2026-07-20T00:00:00Z",
            "pending_feedback_refs": ["feedback-001"],
        }

        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.product-context-bundle",
                payload,
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )

        self.assertEqual(captured.exception.code, ErrorCode.PRODUCT_CONTEXT_CONTAMINATED)

    def test_rule_scope_rejects_extra_owner_keys_and_provider_model_binding(self) -> None:
        base = {
            "rule_id": "rule-001",
            "rule_version": "1.0.0",
            "rule_scope": "product",
            "scope_key": {"product_id": "product-001"},
            "bindings": {},
            "status": "approved",
            "effective_period": {},
            "content_digest": "sha256:" + "1" * 64,
        }

        with self.assertRaises(ContractError) as captured_key:
            validate_payload(
                "avp.contract.rule-ref",
                {**base, "scope_key": {"product_id": "product-001", "sku_id": "sku-001"}},
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )
        self.assertEqual(captured_key.exception.code, ErrorCode.RULE_SCOPE_KEY_REQUIRED)

        with self.assertRaises(ContractError) as captured_binding:
            validate_payload(
                "avp.contract.rule-ref",
                {**base, "bindings": {"provider_model": "synthetic-model"}},
                producer_component_id="product-knowledge",
                producer_agent="skill",
            )
        self.assertEqual(captured_binding.exception.code, ErrorCode.RULE_BINDING_MISMATCH)


if __name__ == "__main__":
    unittest.main()
