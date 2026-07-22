from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ai_video_platform.contracts.errors import ContractError, ErrorCode
from ai_video_platform.skills.product_knowledge import (
    InMemoryProductLibrary,
    FilesystemProductLibrary,
    ProductKnowledgeError,
    ProductKnowledgeErrorCode,
    ProductKnowledgeService,
)


class ProductKnowledgeFailureTests(unittest.TestCase):
    def test_non_owner_write_is_rejected_and_error_details_are_redacted(self) -> None:
        library = InMemoryProductLibrary()
        with self.assertRaises(ProductKnowledgeError) as captured:
            library.commit(
                writer_authority=object(),
                command="write-product",
                idempotency_key="forbidden-write-001",
                input_digest="sha256:" + "0" * 64,
                actor="skill:storyboard",
                reason="Synthetic forbidden write",
                expected_revision=0,
                update=lambda state: {"should_not_run": True},
            )
        self.assertEqual(captured.exception.code, ProductKnowledgeErrorCode.PRODUCT_LIBRARY_WRITE_FORBIDDEN)
        self.assertEqual(library.snapshot()["revision"], 0)

        sanitized = ProductKnowledgeError(
            ProductKnowledgeErrorCode.PRODUCT_LIBRARY_WRITE_FORBIDDEN,
            "Synthetic error",
            details={
                "api_key": "synthetic-sensitive-material",
                "nested": {"authorization": "synthetic-sensitive-material"},
                "safe": "visible",
            },
        ).to_dict()
        self.assertEqual(sanitized["details"]["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["details"]["nested"]["authorization"], "[REDACTED]")
        self.assertEqual(sanitized["details"]["safe"], "visible")

    def test_feedback_id_is_immutable_across_distinct_commands(self) -> None:
        library = InMemoryProductLibrary()
        service = ProductKnowledgeService(library)
        event = {
            "feedback_id": "feedback-immutable-001",
            "task_id": "task-001",
            "source_skill_id": "storyboard",
            "feedback_type": "observation",
            "statement": "Original synthetic statement",
            "evidence_refs": ["evidence:synthetic"],
            "rule_scope": "global",
            "scope_key": {},
            "bindings": {},
            "observed_at": "2026-07-20T00:00:00Z",
            "submitted_by": "skill:storyboard",
        }
        base_request = {
            "event": event,
            "producer_component_id": "storyboard",
            "producer_agent": "skill",
            "actor": "skill:storyboard",
            "reason": "Synthetic immutable feedback",
            "idempotency_key": "immutable-feedback-a",
            "expected_library_revision": 0,
        }
        service.record_feedback(base_request)
        with self.assertRaises(ProductKnowledgeError) as captured:
            service.record_feedback(
                {
                    **base_request,
                    "event": {**event, "statement": "Attempted replacement"},
                    "idempotency_key": "immutable-feedback-b",
                    "expected_library_revision": 1,
                }
            )
        self.assertEqual(captured.exception.code, ProductKnowledgeErrorCode.FEEDBACK_EVENT_IMMUTABLE)
        self.assertEqual(
            library.snapshot()["feedback_events"]["feedback-immutable-001"]["event"]["statement"],
            "Original synthetic statement",
        )
        self.assertEqual(library.snapshot()["revision"], 1)

    def test_product_knowledge_cannot_emit_feedback_and_qa_cannot_approve_promotion(self) -> None:
        library = InMemoryProductLibrary()
        service = ProductKnowledgeService(library)
        product = service.create_product(
            {
                "identity": {"brand": "Acme", "model": "Glow"},
                "evidence_refs": ["evidence:synthetic-catalog"],
                "actor": "human:test",
                "reason": "Synthetic product",
                "idempotency_key": "authority-product",
                "expected_library_revision": 0,
            }
        )
        event = {
            "feedback_id": "feedback-authority-001",
            "task_id": "task-001",
            "source_skill_id": "product-knowledge",
            "feedback_type": "rule_candidate",
            "statement": "Synthetic statement",
            "evidence_refs": ["evidence:synthetic-001"],
            "rule_scope": "product",
            "scope_key": {"product_id": product["product_id"]},
            "bindings": {},
            "observed_at": "2026-07-20T00:00:00Z",
            "submitted_by": "skill:product-knowledge",
            "product_id": product["product_id"],
        }
        with self.assertRaises(ContractError) as self_emit:
            service.record_feedback(
                {
                    "event": event,
                    "producer_component_id": "product-knowledge",
                    "producer_agent": "skill",
                    "actor": "product-knowledge",
                    "reason": "Synthetic forbidden emission",
                    "idempotency_key": "self-feedback",
                    "expected_library_revision": 1,
                }
            )
        self.assertEqual(self_emit.exception.code, ErrorCode.CONTRACT_PRODUCER_FORBIDDEN)
        self.assertEqual(library.snapshot()["revision"], 1)

        event.update({"source_skill_id": "qa-review", "submitted_by": "skill:qa-review"})
        recorded = service.record_feedback(
            {
                "event": event,
                "producer_component_id": "qa-review",
                "producer_agent": "skill",
                "actor": "skill:qa-review",
                "reason": "Synthetic QA feedback",
                "idempotency_key": "qa-feedback",
                "expected_library_revision": 1,
            }
        )
        subject = {"contract_id": event["feedback_id"], "digest": recorded["event_digest"]}
        with self.assertRaises(ContractError) as qa_approval:
            service.confirm_feedback(
                {
                    "feedback_id": event["feedback_id"],
                    "action": "confirmed",
                    "review_decision": {
                        "review_decision_id": "review-authority-001",
                        "subject_ref": subject,
                        "decision": "approve",
                        "decided_by": "qa-review:synthetic",
                        "decided_at": "2026-07-20T01:00:00Z",
                        "criteria_results": [],
                        "evidence_refs": ["evidence:synthetic-001"],
                    },
                    "review_producer": {"component_id": "qa-review", "agent": "skill"},
                    "approval_record": {
                        "approval_id": "approval-authority-001",
                        "subject_ref": subject,
                        "approval_type": "product-knowledge-promotion",
                        "outcome": "approved",
                        "authority": {"authority_id": "qa-review"},
                        "decided_at": "2026-07-20T01:01:00Z",
                        "decision_ref": "review-authority-001",
                    },
                    "approval_producer": {"component_id": "qa-review", "agent": "skill"},
                    "actor": "product-knowledge",
                    "reason": "Synthetic forbidden QA approval",
                    "idempotency_key": "qa-confirm",
                    "expected_library_revision": 2,
                }
            )
        self.assertEqual(qa_approval.exception.code, ErrorCode.APPROVAL_AUTHORITY_INVALID)
        self.assertEqual(library.snapshot()["revision"], 2)

    def test_restore_rejects_tampered_snapshot_and_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "product-library"
            library = FilesystemProductLibrary(root)
            service = ProductKnowledgeService(library)
            service.create_product(
                {
                    "identity": {"brand": "Acme", "model": "Glow"},
                    "evidence_refs": ["evidence:synthetic-catalog"],
                    "actor": "human:test",
                    "reason": "Synthetic product",
                    "idempotency_key": "backup-product",
                    "expected_library_revision": 0,
                }
            )
            snapshot = service.backup_library({"actor": "operator:test", "reason": "Synthetic backup"})
            state_path = snapshot / "library.json"
            state_path.write_text(
                state_path.read_text(encoding="utf-8").replace('"revision":1', '"revision":0'),
                encoding="utf-8",
            )
            with self.assertRaises(ProductKnowledgeError) as tampered:
                service.restore_library(
                    {
                        "snapshot_path": snapshot,
                        "expected_library_revision": 1,
                        "actor": "operator:test",
                        "reason": "Synthetic tamper test",
                    }
                )
            self.assertEqual(tampered.exception.code, ProductKnowledgeErrorCode.BACKUP_INTEGRITY_FAILED)
            self.assertEqual(library.snapshot()["revision"], 1)

            outside = Path(directory) / "outside-snapshot"
            outside.mkdir()
            with self.assertRaises(ProductKnowledgeError) as escaped:
                service.restore_library(
                    {
                        "snapshot_path": outside,
                        "expected_library_revision": 1,
                        "actor": "operator:test",
                        "reason": "Synthetic path escape",
                    }
                )
            self.assertEqual(escaped.exception.code, ProductKnowledgeErrorCode.PRODUCT_LIBRARY_PATH_FORBIDDEN)

    def test_invalid_provenance_missing_product_and_stale_aggregate_use_stable_errors(self) -> None:
        library = InMemoryProductLibrary()
        service = ProductKnowledgeService(library)
        created = service.create_product(
            {
                "identity": {"brand": "Acme", "model": "Glow"},
                "evidence_refs": ["evidence:synthetic-catalog"],
                "actor": "human:test",
                "reason": "Synthetic product",
                "idempotency_key": "stable-error-product",
                "expected_library_revision": 0,
            }
        )
        with self.assertRaises(ProductKnowledgeError) as provenance:
            service.ingest_product(
                {
                    "product_id": created["product_id"],
                    "facts": [
                        {
                            "fact_id": "fact-without-provenance",
                            "claim_type": "color",
                            "value": "red",
                            "status": "confirmed",
                            "inferred": False,
                            "provenance": [],
                        }
                    ],
                    "actor": "human:test",
                    "reason": "Synthetic invalid fact",
                    "idempotency_key": "missing-provenance",
                    "expected_product_version": 1,
                    "expected_library_revision": 1,
                }
            )
        self.assertEqual(provenance.exception.code, ProductKnowledgeErrorCode.VALIDATION_FAILED)
        self.assertEqual(library.snapshot()["revision"], 1)

        with self.assertRaises(ProductKnowledgeError) as missing:
            service.create_sku(
                {
                    "product_id": "missing-product",
                    "identity": {"sku_code": "MISSING"},
                    "evidence_refs": ["evidence:synthetic"],
                    "actor": "human:test",
                    "reason": "Synthetic missing product",
                    "idempotency_key": "missing-product-sku",
                    "expected_product_version": 1,
                    "expected_library_revision": 1,
                }
            )
        self.assertEqual(missing.exception.code, ProductKnowledgeErrorCode.PRODUCT_NOT_FOUND)

        with self.assertRaises(ProductKnowledgeError) as stale:
            service.create_sku(
                {
                    "product_id": created["product_id"],
                    "identity": {"sku_code": "STALE"},
                    "evidence_refs": ["evidence:synthetic"],
                    "actor": "human:test",
                    "reason": "Synthetic stale product",
                    "idempotency_key": "stale-product-sku",
                    "expected_product_version": 99,
                    "expected_library_revision": 1,
                }
            )
        self.assertEqual(stale.exception.code, ProductKnowledgeErrorCode.AGGREGATE_VERSION_CONFLICT)
        self.assertTrue(stale.exception.retryable)
        self.assertEqual(library.snapshot()["revision"], 1)

    def test_noncanonical_rule_scope_and_provider_binding_are_rejected_before_write(self) -> None:
        library = InMemoryProductLibrary()
        service = ProductKnowledgeService(library)
        base_event = {
            "feedback_id": "feedback-invalid-scope",
            "task_id": "task-001",
            "source_skill_id": "storyboard",
            "feedback_type": "rule_candidate",
            "statement": "Synthetic invalid rule candidate",
            "evidence_refs": ["evidence:synthetic"],
            "rule_scope": "provider_model",
            "scope_key": {"provider_id": "provider-a"},
            "bindings": {},
            "observed_at": "2026-07-20T00:00:00Z",
            "submitted_by": "skill:storyboard",
        }
        request = {
            "event": base_event,
            "producer_component_id": "storyboard",
            "producer_agent": "skill",
            "actor": "skill:storyboard",
            "reason": "Synthetic invalid scope",
            "idempotency_key": "invalid-scope",
            "expected_library_revision": 0,
        }
        with self.assertRaises(ContractError) as scope:
            service.record_feedback(request)
        self.assertEqual(scope.exception.code, ErrorCode.RULE_SCOPE_INVALID)

        mismatch = {
            **base_event,
            "feedback_id": "feedback-provider-mismatch",
            "rule_scope": "provider",
            "bindings": {"provider_id": "provider-b", "model_id": "model-a"},
        }
        with self.assertRaises(ContractError) as binding:
            service.record_feedback({**request, "event": mismatch, "idempotency_key": "provider-mismatch"})
        self.assertEqual(binding.exception.code, ErrorCode.RULE_BINDING_MISMATCH)
        self.assertEqual(library.snapshot()["revision"], 0)

    def test_high_confidence_duplicate_product_creation_is_blocked_for_review(self) -> None:
        library = InMemoryProductLibrary()
        service = ProductKnowledgeService(library)
        request = {
            "identity": {"brand": "Acme", "model": "Glow", "name": "Glow Lamp"},
            "evidence_refs": ["evidence:synthetic-catalog-a"],
            "actor": "human:test",
            "reason": "Synthetic product",
            "idempotency_key": "duplicate-product-a",
            "expected_library_revision": 0,
        }
        first = service.create_product(request)
        with self.assertRaises(ProductKnowledgeError) as duplicate:
            service.create_product(
                {
                    **request,
                    "evidence_refs": ["evidence:synthetic-catalog-b"],
                    "idempotency_key": "duplicate-product-b",
                    "expected_library_revision": 1,
                }
            )
        self.assertEqual(duplicate.exception.code, ProductKnowledgeErrorCode.PRODUCT_MATCH_AMBIGUOUS)
        self.assertEqual(duplicate.exception.details["candidate_product_ids"], (first["product_id"],))
        self.assertEqual(library.snapshot()["revision"], 1)

    def test_identification_requires_evidence_and_matching_rejects_empty_or_unknown_clues(self) -> None:
        library = InMemoryProductLibrary()
        service = ProductKnowledgeService(library)
        with self.assertRaises(ProductKnowledgeError) as no_evidence:
            service.identify_product({"clues": {"brand": "Acme"}, "evidence_refs": []})
        self.assertEqual(no_evidence.exception.code, ProductKnowledgeErrorCode.VALIDATION_FAILED)
        with self.assertRaises(ProductKnowledgeError) as no_clues:
            service.match_product({"clues": {}})
        self.assertEqual(no_clues.exception.code, ProductKnowledgeErrorCode.VALIDATION_FAILED)

        service.create_product(
            {
                "identity": {"brand": "Acme", "model": "Glow"},
                "evidence_refs": ["evidence:synthetic"],
                "actor": "human:test",
                "reason": "Synthetic product",
                "idempotency_key": "clue-product",
                "expected_library_revision": 0,
            }
        )
        unknown = service.match_product({"clues": {"brand": "Acme", "unknown_field": "anything"}})
        self.assertEqual(unknown["status"], "no_match")


if __name__ == "__main__":
    unittest.main()
