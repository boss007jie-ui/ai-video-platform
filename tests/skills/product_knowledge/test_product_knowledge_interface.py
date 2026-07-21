from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.contracts.serialization import content_digest
from ai_video_platform.skills.product_knowledge.cli import main as cli_main

from ai_video_platform.skills.product_knowledge import (
    InMemoryProductLibrary,
    ProductKnowledgeError,
    ProductKnowledgeService,
    ProductKnowledgeErrorCode,
)


class ProductKnowledgeInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library = InMemoryProductLibrary()
        self.service = ProductKnowledgeService(self.library)

    def test_identify_match_and_multi_sku_ambiguity(self) -> None:
        identified = self.service.identify_product(
            {
                "clues": {"brand": "Acme", "model": "Glow", "sku_code": "GLOW-RED"},
                "evidence_refs": ["evidence:synthetic-catalog"],
            }
        )
        self.assertEqual(identified["normalized_clues"]["brand"], "acme")
        self.assertEqual(identified["confidence"], "high")

        created = self.service.create_product(
            {
                "identity": {"brand": "Acme", "model": "Glow", "name": "Glow Lamp"},
                "evidence_refs": ["evidence:synthetic-catalog"],
                "actor": "human:test",
                "reason": "Synthetic catalog registration",
                "idempotency_key": "create-product-001",
                "expected_library_revision": 0,
            }
        )
        product_id = created["product_id"]
        self.service.create_sku(
            {
                "product_id": product_id,
                "identity": {"sku_code": "GLOW-RED", "color": "red"},
                "evidence_refs": ["evidence:synthetic-red"],
                "actor": "human:test",
                "reason": "Synthetic red variant",
                "idempotency_key": "create-sku-red",
                "expected_product_version": 1,
                "expected_library_revision": 1,
            }
        )
        self.service.create_sku(
            {
                "product_id": product_id,
                "identity": {"sku_code": "GLOW-BLUE", "color": "blue"},
                "evidence_refs": ["evidence:synthetic-blue"],
                "actor": "human:test",
                "reason": "Synthetic blue variant",
                "idempotency_key": "create-sku-blue",
                "expected_product_version": 2,
                "expected_library_revision": 2,
            }
        )

        exact = self.service.match_product({"clues": {"sku_code": "GLOW-RED"}})
        self.assertEqual(exact["status"], "exact")
        self.assertEqual(exact["product_id"], product_id)

        with self.assertRaises(ProductKnowledgeError) as captured:
            self.service.match_product({"clues": {"brand": "Acme", "model": "Glow"}})
        self.assertEqual(captured.exception.code, ProductKnowledgeErrorCode.PRODUCT_MATCH_AMBIGUOUS)
        self.assertEqual(len(captured.exception.details["sku_candidates"]), 2)

    def test_confirmed_context_excludes_pending_conflicted_and_inferred_facts(self) -> None:
        created = self.service.create_product(
            {
                "identity": {"brand": "Acme", "model": "Glow"},
                "evidence_refs": ["evidence:synthetic-catalog"],
                "actor": "human:test",
                "reason": "Synthetic catalog registration",
                "idempotency_key": "context-product",
                "expected_library_revision": 0,
            }
        )
        product_id = created["product_id"]
        self.service.ingest_product(
            {
                "product_id": product_id,
                "facts": [
                    {
                        "fact_id": "fact-confirmed",
                        "claim_type": "color",
                        "value": "red",
                        "status": "confirmed",
                        "inferred": False,
                        "provenance": ["evidence:synthetic-confirmed"],
                    },
                    {
                        "fact_id": "fact-pending",
                        "claim_type": "weight",
                        "value": "2kg",
                        "status": "pending",
                        "inferred": False,
                        "provenance": ["evidence:synthetic-pending"],
                    },
                    {
                        "fact_id": "fact-conflicted",
                        "claim_type": "width",
                        "value": "20cm",
                        "status": "conflicted",
                        "inferred": False,
                        "provenance": ["evidence:synthetic-conflict-a", "evidence:synthetic-conflict-b"],
                    },
                    {
                        "fact_id": "fact-inferred",
                        "claim_type": "finish",
                        "value": "matte",
                        "status": "confirmed",
                        "inferred": True,
                        "provenance": ["evidence:synthetic-visual-estimate"],
                    },
                    {
                        "fact_id": "fact-future",
                        "claim_type": "packaging",
                        "value": "seasonal-box",
                        "status": "confirmed",
                        "inferred": False,
                        "provenance": ["evidence:synthetic-future"],
                        "effective_period": {"valid_from": "2026-07-21T00:00:00Z"},
                    },
                ],
                "actor": "human:test",
                "reason": "Synthetic fact intake",
                "idempotency_key": "facts-001",
                "expected_product_version": 1,
                "expected_library_revision": 1,
            }
        )

        context = self.service.build_product_context(
            {"product_id": product_id, "purpose": "storyboard", "at": "2026-07-20T00:00:00Z"}
        )
        replayed_context = self.service.build_product_context(
            {"product_id": product_id, "purpose": "storyboard", "at": "2026-07-20T00:00:00Z"}
        )
        self.assertEqual(replayed_context, context)
        self.assertEqual([fact["fact_id"] for fact in context["facts"]], ["fact-confirmed"])
        self.assertEqual(context["facts"][0]["provenance"], ["evidence:synthetic-confirmed"])

        review = self.service.build_product_review_context(
            {"product_id": product_id, "at": "2026-07-20T00:00:00Z"}
        )
        self.assertEqual(
            {item["review_item_id"] for item in review["review_items"]},
            {"fact-pending", "fact-conflicted", "fact-inferred"},
        )

    def test_feedback_is_immutable_deduplicated_and_promoted_only_with_approval(self) -> None:
        created = self.service.create_product(
            {
                "identity": {"brand": "Acme", "model": "Glow"},
                "evidence_refs": ["evidence:synthetic-catalog"],
                "actor": "human:test",
                "reason": "Synthetic catalog registration",
                "idempotency_key": "feedback-product",
                "expected_library_revision": 0,
            }
        )
        product_id = created["product_id"]
        event = {
            "feedback_id": "feedback-001",
            "task_id": "task-001",
            "source_skill_id": "storyboard",
            "feedback_type": "visual_constraint",
            "statement": "Keep the logo centered",
            "evidence_refs": ["evidence:frame-001"],
            "rule_scope": "product",
            "scope_key": {"product_id": product_id},
            "bindings": {},
            "observed_at": "2026-07-20T00:00:00Z",
            "submitted_by": "skill:storyboard",
            "product_id": product_id,
            "suggested_rule": {"content": "Keep the logo centered"},
        }
        recorded = self.service.record_feedback(
            {
                "event": event,
                "producer_component_id": "storyboard",
                "producer_agent": "skill",
                "actor": "skill:storyboard",
                "reason": "Synthetic feedback intake",
                "idempotency_key": "feedback-ingest-001",
                "expected_library_revision": 1,
            }
        )
        event["statement"] = "mutated after intake"
        duplicate = self.service.record_feedback(
            {
                "event": {
                    **event,
                    "feedback_id": "feedback-002",
                    "statement": "  keep   the LOGO centered  ",
                    "submitted_by": "human:reviewer",
                },
                "producer_component_id": "authorized-human-review-interface",
                "producer_agent": "human",
                "actor": "human:reviewer",
                "reason": "Synthetic duplicate intake",
                "idempotency_key": "feedback-ingest-002",
                "expected_library_revision": 2,
            }
        )
        self.assertEqual(duplicate["duplicate_of"], "feedback-001")
        self.assertEqual(self.library.snapshot()["feedback_events"]["feedback-001"]["event"]["statement"], "Keep the logo centered")

        subject_ref = {"contract_id": "feedback-001", "digest": recorded["event_digest"]}
        review = {
            "review_decision_id": "review-001",
            "subject_ref": subject_ref,
            "decision": "approve",
            "decided_by": "human:reviewer",
            "decided_at": "2026-07-20T01:00:00Z",
            "criteria_results": [],
            "evidence_refs": ["evidence:frame-001"],
        }
        approval = {
            "approval_id": "approval-001",
            "subject_ref": subject_ref,
            "approval_type": "product-knowledge-promotion",
            "outcome": "approved",
            "authority": {"authority_id": "synthetic-approval-boundary"},
            "decided_at": "2026-07-20T01:01:00Z",
            "decision_ref": "review-001",
        }
        confirmed = self.service.confirm_feedback(
            {
                "feedback_id": "feedback-001",
                "action": "confirmed",
                "review_decision": review,
                "review_producer": {"component_id": "authorized-human-review-interface", "agent": "human"},
                "approval_record": approval,
                "approval_producer": {"component_id": "authorized-approval-boundary", "agent": "system"},
                "actor": "product-knowledge",
                "reason": "Synthetic approved promotion",
                "idempotency_key": "confirm-feedback-001",
                "expected_library_revision": 3,
            }
        )
        self.assertEqual(confirmed["status"], "confirmed")

        consolidated = self.service.consolidate_learning(
            {
                "feedback_ids": ["feedback-001"],
                "effective_period": {
                    "valid_from": "2026-07-20T01:01:00Z",
                    "valid_until": "2026-07-21T01:01:00Z",
                },
                "actor": "product-knowledge",
                "reason": "Synthetic rule consolidation",
                "idempotency_key": "consolidate-001",
                "expected_library_revision": 4,
            }
        )
        self.assertEqual(consolidated["rule_refs"][0]["rule_scope"], "product")
        self.assertEqual(
            consolidated["rule_refs"][0]["content_digest"],
            content_digest({"content": "Keep the logo centered"}),
        )
        before = self.service.build_product_context(
            {"product_id": product_id, "purpose": "storyboard", "at": "2026-07-20T01:00:00Z"}
        )
        active = self.service.build_product_context(
            {"product_id": product_id, "purpose": "storyboard", "at": "2026-07-20T02:00:00Z"}
        )
        expired = self.service.build_product_context(
            {"product_id": product_id, "purpose": "storyboard", "at": "2026-07-22T02:00:00Z"}
        )
        self.assertEqual(before["rule_refs"], [])
        self.assertEqual(len(active["rule_refs"]), 1)
        self.assertEqual(expired["rule_refs"], [])

    def test_asset_organization_publishes_only_approved_assets(self) -> None:
        created = self.service.create_product(
            {
                "identity": {"brand": "Acme", "model": "Glow"},
                "evidence_refs": ["evidence:synthetic-catalog"],
                "actor": "human:test",
                "reason": "Synthetic product",
                "idempotency_key": "asset-product",
                "expected_library_revision": 0,
            }
        )
        product_id = created["product_id"]
        organized = self.service.organize_assets(
            {
                "manifest": {
                    "manifest_id": "manifest-001",
                    "manifest_revision": 1,
                    "owner_type": "product",
                    "owner_id": product_id,
                    "assets": [
                        {
                            "asset_id": "asset-approved",
                            "role": "product",
                            "media_type": "image/png",
                            "uri": "file:///synthetic/approved.png",
                            "sha256": "1" * 64,
                            "byte_size": 128,
                            "provenance": {"evidence_refs": ["evidence:asset-approved"]},
                            "created_at": "2026-07-20T00:00:00Z",
                            "approval_state": "approved",
                        },
                        {
                            "asset_id": "asset-pending",
                            "role": "packaging",
                            "media_type": "image/png",
                            "uri": "file:///synthetic/pending.png",
                            "sha256": "2" * 64,
                            "byte_size": 256,
                            "provenance": {"evidence_refs": ["evidence:asset-pending"]},
                            "created_at": "2026-07-20T00:00:00Z",
                            "approval_state": "pending",
                            "relations": [{"relation": "replacement", "target_asset_id": "asset-approved"}],
                        },
                    ],
                    "created_at": "2026-07-20T00:00:00Z",
                },
                "actor": "human:test",
                "reason": "Synthetic asset organization",
                "idempotency_key": "organize-assets-001",
                "expected_product_version": 1,
                "expected_library_revision": 1,
            }
        )
        self.assertEqual(organized["asset_ids"], ["asset-approved", "asset-pending"])

        context = self.service.build_product_context(
            {"product_id": product_id, "purpose": "storyboard", "at": "2026-07-20T00:00:00Z"}
        )
        self.assertEqual(context["approved_asset_refs"], ["asset-approved"])
        review = self.service.build_product_review_context(
            {"product_id": product_id, "at": "2026-07-20T00:00:00Z"}
        )
        self.assertEqual([item["review_item_id"] for item in review["review_items"]], ["asset-pending"])

    def test_conflict_resolution_preserves_history_and_requires_separate_approval(self) -> None:
        created = self.service.create_product(
            {
                "identity": {"brand": "Acme", "model": "Glow"},
                "evidence_refs": ["evidence:synthetic-catalog"],
                "actor": "human:test",
                "reason": "Synthetic product",
                "idempotency_key": "conflict-product",
                "expected_library_revision": 0,
            }
        )
        product_id = created["product_id"]
        ingested = self.service.ingest_product(
            {
                "product_id": product_id,
                "facts": [
                    {
                        "fact_id": "fact-color-conflict",
                        "claim_type": "color",
                        "value": "red-or-blue",
                        "candidate_values": ["red", "blue"],
                        "status": "conflicted",
                        "inferred": False,
                        "provenance": ["evidence:red", "evidence:blue"],
                    }
                ],
                "actor": "human:test",
                "reason": "Synthetic conflict intake",
                "idempotency_key": "conflict-ingest",
                "expected_product_version": 1,
                "expected_library_revision": 1,
            }
        )
        conflict_ref = ingested["conflict_refs"][0]
        subject = {"contract_id": conflict_ref["conflict_id"], "digest": conflict_ref["digest"]}
        resolved = self.service.resolve_conflict(
            {
                "conflict_id": conflict_ref["conflict_id"],
                "selected_value": "red",
                "review_decision": {
                    "review_decision_id": "review-conflict-001",
                    "subject_ref": subject,
                    "decision": "approve",
                    "decided_by": "human:reviewer",
                    "decided_at": "2026-07-20T01:00:00Z",
                    "criteria_results": [],
                    "evidence_refs": ["evidence:red"],
                },
                "review_producer": {"component_id": "authorized-human-review-interface", "agent": "human"},
                "approval_record": {
                    "approval_id": "approval-conflict-001",
                    "subject_ref": subject,
                    "approval_type": "product-fact-resolution",
                    "outcome": "approved",
                    "authority": {"authority_id": "synthetic-approval-boundary"},
                    "decided_at": "2026-07-20T01:01:00Z",
                    "decision_ref": "review-conflict-001",
                },
                "approval_producer": {"component_id": "authorized-approval-boundary", "agent": "system"},
                "actor": "product-knowledge",
                "reason": "Synthetic conflict resolution",
                "idempotency_key": "resolve-conflict-001",
                "expected_product_version": 2,
                "expected_library_revision": 2,
            }
        )
        self.assertEqual(resolved["status"], "resolved")
        context = self.service.build_product_context(
            {"product_id": product_id, "purpose": "storyboard", "at": "2026-07-20T02:00:00Z"}
        )
        self.assertEqual([(fact["value"], fact["status"]) for fact in context["facts"]], [("red", "confirmed")])
        state = self.library.snapshot()
        original = next(fact for fact in state["products"][product_id]["facts"] if fact["fact_id"] == "fact-color-conflict")
        self.assertEqual(original["status"], "superseded")

    def test_cli_emits_machine_result_execution_event_and_stable_validation_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = StringIO()
            error = StringIO()
            exit_code = cli_main(
                ["identify-product", "--library", str(Path(directory) / "library"), "--input", "-"],
                stdin=StringIO(
                    json.dumps(
                        {
                            "task_id": "task-cli-001",
                            "clues": {"brand": "Acme", "model": "Glow", "sku_code": "GLOW-RED"},
                            "evidence_refs": ["evidence:synthetic-cli"],
                        }
                    )
                ),
                stdout=output,
                stderr=error,
            )
            self.assertEqual(exit_code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["result"]["confidence"], "high")
            self.assertEqual(payload["execution_event"]["skill_id"], "product-knowledge")
            self.assertEqual(payload["execution_event"]["event_type"], "completed")
            self.assertEqual(error.getvalue(), "")

            bad_output = StringIO()
            bad_exit = cli_main(
                ["identify-product", "--library", str(Path(directory) / "library"), "--input", "-"],
                stdin=StringIO("{}"),
                stdout=bad_output,
                stderr=StringIO(),
            )
            self.assertEqual(bad_exit, 2)
            failure = json.loads(bad_output.getvalue())
            self.assertFalse(failure["ok"])
            self.assertEqual(failure["error"]["code"], "VALIDATION_FAILED")

    def test_feedback_intake_mechanically_accepts_exactly_six_rule_scopes(self) -> None:
        cases = {
            "product": ({"product_id": "product-synthetic"}, {}),
            "sku": ({"product_id": "product-synthetic", "sku_id": "sku-synthetic"}, {}),
            "category": ({"category_id": "category-synthetic"}, {}),
            "skill": ({"skill_id": "storyboard"}, {}),
            "provider": (
                {"provider_id": "provider-synthetic"},
                {"provider_id": "provider-synthetic", "model_id": "model-synthetic", "version": "1"},
            ),
            "global": ({}, {"region": "synthetic-region"}),
        }
        for index, (scope, (scope_key, bindings)) in enumerate(cases.items()):
            recorded = self.service.record_feedback(
                {
                    "event": {
                        "feedback_id": f"feedback-scope-{scope}",
                        "task_id": "task-scope-001",
                        "source_skill_id": "storyboard",
                        "feedback_type": "rule_candidate",
                        "statement": f"Synthetic {scope} rule candidate",
                        "evidence_refs": [f"evidence:scope-{scope}"],
                        "rule_scope": scope,
                        "scope_key": scope_key,
                        "bindings": bindings,
                        "observed_at": "2026-07-20T00:00:00Z",
                        "submitted_by": "skill:storyboard",
                    },
                    "producer_component_id": "storyboard",
                    "producer_agent": "skill",
                    "actor": "skill:storyboard",
                    "reason": "Synthetic scope verification",
                    "idempotency_key": f"scope-{scope}",
                    "expected_library_revision": index,
                }
            )
            self.assertEqual(recorded["status"], "pending_review")
        self.assertEqual(len(self.library.snapshot()["feedback_events"]), 6)


if __name__ == "__main__":
    unittest.main()
