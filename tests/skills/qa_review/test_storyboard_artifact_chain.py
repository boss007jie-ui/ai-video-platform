from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.qa_review import ReviewOutcome, ReviewRequest, review
from ai_video_platform.skills.qa_review.cli import main as cli_main


PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_CASES = PROJECT_ROOT / "fixtures" / "golden" / "qa_review" / "storyboard-chain-cases-v1.json"


def valid_composition_request() -> dict[str, object]:
    revision = "planning-rev-1"
    product_context_ref = "contract://product-context-bundle/synthetic-v1"
    panel_asset = "asset://production-panel/panel-001-clean"
    return {
        "schema_version": "1.0.0",
        "criteria_version": "storyboard-chain-qa-v1",
        "evaluation_set_version": "storyboard-chain-eval-v1",
        "command": "review-composition",
        "task_id": "task-storyboard-chain-qa",
        "execution_id": "exec-storyboard-chain-pass",
        "subject": {
            "artifact_id": "storyboard-chain-synthetic-v1",
            "artifact_type": "StoryboardArtifactChain",
            "schema_version": "1.0.0",
            "revision": revision,
            "contract_valid": True,
            "product_context_bundle": {
                "artifact_ref": product_context_ref,
                "revision": revision,
                "product_id": "product-001",
                "sku_id": "sku-001",
                "approved_asset_refs": ["asset://approved/product-001"],
                "immutable_hash": "sha256:" + "a" * 64,
            },
            "artifacts": [
                {
                    "artifact_id": "beat-001",
                    "artifact_type": "avp.contract.reference-beat",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "reference-analysis",
                    "immutable_hash": "sha256:" + "b" * 64,
                    "upstream_refs": ["asset://sanitized/reference-video-001"],
                    "start_ms": 0,
                    "end_ms": 6000,
                },
                {
                    "artifact_id": "evidence-001",
                    "artifact_type": "avp.contract.reference-shot-evidence",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "reference-analysis",
                    "immutable_hash": "sha256:" + "c" * 64,
                    "upstream_refs": ["asset://sanitized/reference-video-001"],
                    "start_ms": 0,
                    "end_ms": 6000,
                    "keyframe_refs": ["asset://sanitized/keyframe-001"],
                },
                {
                    "artifact_id": "pattern-001",
                    "artifact_type": "avp.contract.replication-pattern",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "reference-analysis",
                    "immutable_hash": "sha256:" + "d" * 64,
                    "upstream_refs": ["beat-001", "evidence-001"],
                    "mechanism": "three-beat-problem-solution-demo",
                },
                {
                    "artifact_id": "board-manifest-001",
                    "artifact_type": "avp.contract.reference-analysis-board-manifest",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "reference-analysis",
                    "immutable_hash": "sha256:" + "e" * 64,
                    "upstream_refs": ["beat-001", "evidence-001", "pattern-001"],
                    "asset_refs": ["asset://reference-analysis/reference-storyboard-analysis-board"],
                },
                {
                    "artifact_id": "analysis-001",
                    "artifact_type": "avp.contract.reference-storyboard-analysis",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "reference-analysis",
                    "immutable_hash": "sha256:" + "1" * 64,
                    "upstream_refs": ["beat-001", "evidence-001", "pattern-001"],
                    "source_metadata": {
                        "source_ref": "asset://sanitized/reference-video-001",
                        "duration_ms": 12000,
                    },
                    "beats": [{"start_ms": 0, "end_ms": 6000}],
                    "shot_evidence": [
                        {
                            "start_ms": 0,
                            "end_ms": 6000,
                            "keyframe_refs": ["asset://sanitized/keyframe-001"],
                            "source_metadata_ref": "asset://sanitized/reference-video-001",
                            "comment_provenance": ["comment://synthetic/001"],
                        }
                    ],
                    "invented_content": False,
                },
                {
                    "artifact_id": "plan-001",
                    "artifact_type": "avp.contract.production-storyboard-plan",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "storyboard",
                    "immutable_hash": "sha256:" + "2" * 64,
                    "upstream_refs": ["analysis-001", product_context_ref],
                    "product_context_ref": product_context_ref,
                    "product_id": "product-001",
                    "sku_id": "sku-001",
                    "adapted_mechanisms": ["three-beat-problem-solution-demo"],
                    "copied_reference_identity": False,
                    "copied_reference_fields": [],
                },
                {
                    "artifact_id": "panel-plan-001",
                    "artifact_type": "avp.contract.production-storyboard-panel-plan",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "storyboard",
                    "immutable_hash": "sha256:" + "3" * 64,
                    "upstream_refs": ["plan-001", product_context_ref],
                    "product_context_ref": product_context_ref,
                    "panel_order": ["panel-001"],
                },
                {
                    "artifact_id": "panel-set-001",
                    "artifact_type": "avp.contract.production-storyboard-panel-set",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "product-image-panel-generation",
                    "immutable_hash": "sha256:" + "4" * 64,
                    "upstream_refs": ["panel-plan-001", product_context_ref],
                    "product_context_ref": product_context_ref,
                    "product_id": "product-001",
                    "sku_id": "sku-001",
                    "panels": [
                        {
                            "panel_id": "panel-001",
                            "asset_ref": panel_asset,
                            "approved": True,
                            "product_id": "product-001",
                            "aspect_ratio": "9:16",
                            "asset_kind": "production_panel",
                            "source_asset_refs": ["asset://approved/product-001"],
                        }
                    ],
                    "continuity": {
                        "scale": "locked",
                        "character": "locked",
                        "wardrobe": "locked",
                        "product": "locked",
                        "packaging": "locked",
                        "container": "locked",
                        "scene": "locked",
                    },
                },
                {
                    "artifact_id": "master-001",
                    "artifact_type": "avp.contract.video-generation-storyboard-master",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "storyboard-master-video-planning",
                    "immutable_hash": "sha256:" + "5" * 64,
                    "upstream_refs": ["plan-001", "panel-set-001", product_context_ref],
                    "product_context_ref": product_context_ref,
                    "aspect_ratio": "9:16",
                    "shot_order": ["shot-001"],
                    "shots": [
                        {
                            "shot_id": "shot-001",
                            "panel_id": "panel-001",
                            "duration_ms": 6000,
                            "start_state": "sealed",
                            "middle_state": "demonstrating",
                            "end_state": "cta",
                            "motion": "hand opens package",
                            "emotion": "curious",
                            "camera": "medium push-in",
                            "transition": "cut",
                            "voiceover": "Synthetic voiceover",
                            "captions": "Synthetic caption",
                            "sound": "soft click",
                            "cta": "Learn more",
                        }
                    ],
                },
                {
                    "artifact_id": "motion-001",
                    "artifact_type": "avp.contract.shot-motion-plan",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "storyboard-master-video-planning",
                    "immutable_hash": "sha256:" + "6" * 64,
                    "upstream_refs": ["master-001", "panel-set-001"],
                    "motions": [{"shot_id": "shot-001", "panel_id": "panel-001", "motion": "hand opens package"}],
                },
                {
                    "artifact_id": "first-frame-001",
                    "artifact_type": "avp.contract.first-frame-mapping",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "storyboard-master-video-planning",
                    "immutable_hash": "sha256:" + "7" * 64,
                    "upstream_refs": ["master-001", "panel-set-001"],
                    "shot_id": "shot-001",
                    "panel_id": "panel-001",
                    "asset_ref": panel_asset,
                    "asset_role": "clean_full_frame_panel",
                    "aspect_ratio": "9:16",
                    "approved": True,
                    "contains_grid": False,
                    "contains_numbering": False,
                    "contains_label": False,
                    "contains_text_overlay": False,
                },
                {
                    "artifact_id": "role-map-001",
                    "artifact_type": "avp.contract.reference-role-mapping",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "storyboard-master-video-planning",
                    "immutable_hash": "sha256:" + "8" * 64,
                    "upstream_refs": ["master-001", "board-manifest-001"],
                    "mappings": [
                        {
                            "asset_ref": "asset://reference-analysis/reference-storyboard-analysis-board",
                            "asset_kind": "reference_analysis_board",
                            "role": "global_structure_reference",
                            "provider_execution_input": False,
                            "first_frame_eligible": False,
                        }
                    ],
                },
                {
                    "artifact_id": "exec-001",
                    "artifact_type": "avp.contract.video-execution-package",
                    "schema_version": "1.0.0",
                    "revision": revision,
                    "producer_component_id": "storyboard-master-video-planning",
                    "immutable_hash": "sha256:" + "9" * 64,
                    "upstream_refs": ["master-001", "motion-001", "first-frame-001", "role-map-001"],
                    "shot_order": ["shot-001"],
                    "panel_order": ["panel-001"],
                    "panel_refs": [panel_asset],
                    "first_frame_mapping_ref": "first-frame-001",
                    "reference_role_mapping_ref": "role-map-001",
                },
            ],
        },
        "criteria": {"expected_revision": revision},
        "context": {
            "product_context_revision": revision,
            "expected_product_context_revision": revision,
        },
        "evidence_refs": ["fixture:storyboard-artifact-chain/synthetic-v1"],
    }


class StoryboardArtifactChainQATests(unittest.TestCase):
    def test_complete_synthetic_composition_passes_all_eight_families(self) -> None:
        result = review(ReviewRequest.from_mapping(valid_composition_request()))

        self.assertEqual(result.outcome, ReviewOutcome.PASS)
        family_results = {
            item["criterion_id"]: item["outcome"]
            for item in result.human_review_package["criteria_results"]
        }
        self.assertEqual(
            family_results,
            {
                "reference-analysis-evidence": "pass",
                "reference-to-production-translation": "pass",
                "production-panel-identity-continuity": "pass",
                "video-storyboard-master-completeness": "pass",
                "first-frame-correctness": "pass",
                "reference-role-mapping": "pass",
                "artifact-misuse-prevention": "pass",
                "end-to-end-provenance": "pass",
            },
        )

    def test_mandatory_blocking_cases_identify_artifact_and_owning_producer(self) -> None:
        cases = (
            (
                "missing-product-context",
                lambda request: request["subject"].pop("product_context_bundle"),
                "QA_PRODUCT_CONTEXT_MISSING",
                "storyboard",
            ),
            (
                "copied-reference-identity",
                lambda request: _artifact(request, "avp.contract.production-storyboard-plan").update(
                    {"copied_reference_identity": True, "copied_reference_fields": ["brand"]}
                ),
                "QA_REFERENCE_IDENTITY_COPIED",
                "storyboard",
            ),
            (
                "panel-product-mismatch",
                lambda request: _artifact(request, "avp.contract.production-storyboard-panel-set").update(
                    {"product_id": "product-wrong"}
                ),
                "QA_PANEL_PRODUCT_MISMATCH",
                "product-image-panel-generation",
            ),
            (
                "missing-master-duration",
                lambda request: _artifact(request, "avp.contract.video-generation-storyboard-master")["shots"][0].pop("duration_ms"),
                "QA_MASTER_FIELD_MISSING",
                "storyboard-master-video-planning",
            ),
            (
                "shot-panel-order-mismatch",
                lambda request: _artifact(request, "avp.contract.video-execution-package").update(
                    {"panel_order": ["panel-wrong"]}
                ),
                "QA_EXECUTION_ORDER_MISMATCH",
                "storyboard-master-video-planning",
            ),
            (
                "unapproved-execution-panel",
                lambda request: _artifact(request, "avp.contract.video-execution-package").update(
                    {"panel_refs": ["asset://production-panel/unapproved"]}
                ),
                "QA_EXECUTION_PANEL_UNAPPROVED",
                "storyboard-master-video-planning",
            ),
            (
                "analysis-board-first-frame",
                lambda request: _artifact(request, "avp.contract.first-frame-mapping").update(
                    {
                        "asset_ref": "asset://reference-analysis/analysis-board",
                        "asset_kind": "reference_analysis_board",
                    }
                ),
                "QA_FORBIDDEN_FIRST_FRAME_ASSET",
                "storyboard-master-video-planning",
            ),
            (
                "unsupported-version",
                lambda request: _artifact(request, "avp.contract.video-execution-package").update(
                    {"schema_version": "0.1.0"}
                ),
                "QA_ARTIFACT_VERSION_UNSUPPORTED",
                "storyboard-master-video-planning",
            ),
            (
                "unsupported-identity",
                lambda request: _artifact(request, "avp.contract.video-execution-package").update(
                    {"artifact_type": "StoryboardMaster"}
                ),
                "QA_ARTIFACT_IDENTITY_UNSUPPORTED",
                "unregistered",
            ),
            (
                "wrong-producer",
                lambda request: _artifact(request, "avp.contract.production-storyboard-panel-set").update(
                    {"producer_component_id": "malicious-producer"}
                ),
                "QA_ARTIFACT_PRODUCER_MISMATCH",
                "product-image-panel-generation",
            ),
            (
                "broken-provenance",
                lambda request: _artifact(request, "avp.contract.production-storyboard-panel-set").update(
                    {"immutable_hash": "missing"}
                ),
                "QA_ARTIFACT_HASH_INVALID",
                "product-image-panel-generation",
            ),
        )

        for case_id, mutate, expected_code, expected_owner in cases:
            with self.subTest(case=case_id):
                request = valid_composition_request()
                request["execution_id"] = f"exec-{case_id}"
                mutate(request)

                result = review(ReviewRequest.from_mapping(request))

                self.assertEqual(result.outcome, ReviewOutcome.FAIL)
                matching = [
                    issue for issue in result.human_review_package["issues"]
                    if issue["code"] == expected_code
                ]
                self.assertTrue(matching, result.human_review_package["issues"])
                self.assertTrue(matching[0]["offending_artifact"])
                self.assertEqual(matching[0]["owning_producer"], expected_owner)

    def test_all_failures_attribute_registered_artifacts_to_the_canonical_owner(self) -> None:
        request = valid_composition_request()
        panel_set = _artifact(request, "avp.contract.production-storyboard-panel-set")
        panel_set.update({"producer_component_id": "malicious-producer", "product_id": "wrong-product"})

        result = review(ReviewRequest.from_mapping(request))

        matching = [
            issue for issue in result.human_review_package["issues"]
            if issue["code"] == "QA_PANEL_PRODUCT_MISMATCH"
        ]
        self.assertTrue(matching)
        self.assertEqual(matching[0]["owning_producer"], "product-image-panel-generation")

    def test_versioned_golden_catalog_covers_positive_and_negative_cases_for_eight_families(self) -> None:
        fixture = json.loads(GOLDEN_CASES.read_text(encoding="utf-8"))
        expected_families = {
            "reference-analysis-evidence",
            "reference-to-production-translation",
            "production-panel-identity-continuity",
            "video-storyboard-master-completeness",
            "first-frame-correctness",
            "reference-role-mapping",
            "artifact-misuse-prevention",
            "end-to-end-provenance",
        }
        observed: dict[str, set[str]] = {family: set() for family in expected_families}
        false_positives = 0
        false_negatives = 0

        for case in fixture["cases"]:
            with self.subTest(case=case["case_id"]):
                request = valid_composition_request()
                request["execution_id"] = f"exec-{case['case_id']}"
                _apply_mutation(request, case["mutation"])
                result = review(ReviewRequest.from_mapping(request))
                expected = ReviewOutcome(case["expected_outcome"])
                observed[case["family"]].add(case["expected_outcome"])
                false_positives += expected is ReviewOutcome.PASS and result.outcome is ReviewOutcome.FAIL
                false_negatives += expected is ReviewOutcome.FAIL and result.outcome is ReviewOutcome.PASS
                self.assertEqual(result.outcome, expected)
                expected_code = case.get("expected_code")
                if expected_code:
                    issues = result.human_review_package["issues"]
                    self.assertIn(expected_code, {issue["code"] for issue in issues})

        self.assertEqual(set(observed), expected_families)
        self.assertTrue(all(outcomes == {"pass", "fail"} for outcomes in observed.values()))
        self.assertEqual(false_positives, 0)
        self.assertEqual(false_negatives, 0)
        self.assertEqual(fixture["provider_calls"], 0)

    def test_public_storyboard_chain_commands_run_offline_and_write_only_qa_outputs(self) -> None:
        for command in ("review-artifact", "review-composition"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                request = valid_composition_request()
                request["command"] = command
                if command == "review-artifact":
                    request["subject"] = deepcopy(
                        _artifact(request, "avp.contract.reference-storyboard-analysis")
                    )
                    request["context"]["available_artifact_refs"] = [
                        "beat-001", "evidence-001", "pattern-001"
                    ]
                request_path = root / "request.json"
                output_dir = root / "output"
                request_path.write_text(json.dumps(request), encoding="utf-8")

                exit_code = cli_main(
                    [command, "--request", str(request_path), "--output-dir", str(output_dir)]
                )

                self.assertEqual(exit_code, 0)
                self.assertEqual(
                    {path.name for path in output_dir.iterdir()},
                    {
                        "feedback-events.json",
                        "human-review-package.json",
                        "result.json",
                        "review-decision.json",
                        "skill-execution-event.json",
                    },
                )
                package = json.loads((output_dir / "human-review-package.json").read_text(encoding="utf-8"))
                self.assertNotIn("approval_record", package)
                self.assertNotIn("provider_result", package)

    def test_structured_qareport_binds_inputs_and_invalidates_readiness(self) -> None:
        request = valid_composition_request()
        request["context"].update(
            {
                "evaluation_inputs": {"panel-set-001": "sha256:" + "4" * 64, "master-001": "sha256:" + "5" * 64},
                "qa_code_commit": "qa-test-commit",
                "python_version": "3.14.0",
            }
        )
        result = review(ReviewRequest.from_mapping(request))
        report = result.human_review_package["qa_report"]
        self.assertEqual(report["decision"], "PASS")
        self.assertEqual(report["readiness"], "READY")
        self.assertEqual(report["evaluation_set"]["input_revisions_digests"]["panel-set-001"], "sha256:" + "4" * 64)
        self.assertEqual(report["qa_code_commit"], "qa-test-commit")
        self.assertFalse(report["owner_artifacts_mutated"])

        stale = valid_composition_request()
        stale["context"].update({"evaluation_inputs": {"panel-set-001": "sha256:" + "0" * 64}})
        stale["subject"]["artifacts"][2]["revision"] = "stale-revision"
        stale_result = review(ReviewRequest.from_mapping(stale))
        stale_report = stale_result.human_review_package["qa_report"]
        self.assertEqual(stale_report["readiness"], "INVALIDATED")
        self.assertTrue(stale_report["execution_artifacts_suppressed"])
        self.assertTrue(stale_report["findings"])
        self.assertTrue(all({"error_code", "severity", "artifact_id", "field_paths"} <= set(item) for item in stale_report["findings"]))

        revoked = valid_composition_request()
        revoked["context"]["withdrawal_authorized"] = True
        revoked["subject"]["artifacts"][2]["revision"] = "stale-revision"
        revoked_result = review(ReviewRequest.from_mapping(revoked))
        self.assertEqual(revoked_result.human_review_package["qa_report"]["readiness"], "REVOKED")

    def test_layered_panel_visual_evidence_hash_mismatch_fails_closed(self) -> None:
        request = valid_composition_request()
        panel = _artifact(request, "avp.contract.production-storyboard-panel-set")["panels"][0]
        panel.update(
            {
                "usage_status": "SELECTED",
                "panel_asset_facts": {"panel_asset_id": "asset-panel-001", "sha256": "sha256:" + "a" * 64, "approval_status": "approved", "qa_status": "pass"},
                "approval_evidence": {"kind": "ApprovalRecord", "panel_asset_id": "asset-panel-001", "asset_sha256": "sha256:" + "b" * 64, "decision": "approved"},
            }
        )
        result = review(ReviewRequest.from_mapping(request))
        self.assertEqual(result.outcome, ReviewOutcome.FAIL)
        self.assertIn("QA_PANEL_VISUAL_EVIDENCE_INVALID", {item["code"] for item in result.human_review_package["issues"]})


def _artifact(request: dict[str, object], artifact_type: str) -> dict[str, object]:
    for artifact in request["subject"]["artifacts"]:
        if artifact["artifact_type"] == artifact_type:
            return artifact
    raise AssertionError(f"Missing test artifact: {artifact_type}")


def _apply_mutation(request: dict[str, object], mutation: str) -> None:
    if mutation == "none":
        return
    if mutation == "remove-keyframes":
        _artifact(request, "avp.contract.reference-storyboard-analysis")["shot_evidence"][0]["keyframe_refs"] = []
    elif mutation == "copy-reference-brand":
        _artifact(request, "avp.contract.production-storyboard-plan").update(
            {"copied_reference_identity": True, "copied_reference_fields": ["brand"]}
        )
    elif mutation == "break-scene-continuity":
        _artifact(request, "avp.contract.production-storyboard-panel-set")["continuity"].pop("scene")
    elif mutation == "remove-shot-motion":
        _artifact(request, "avp.contract.video-generation-storyboard-master")["shots"][0].pop("motion")
    elif mutation == "first-frame-grid":
        _artifact(request, "avp.contract.first-frame-mapping")["contains_grid"] = True
    elif mutation == "make-analysis-board-executable":
        _artifact(request, "avp.contract.reference-role-mapping")["mappings"][0]["provider_execution_input"] = True
    elif mutation == "analysis-board-as-panel":
        _artifact(request, "avp.contract.production-storyboard-panel-set")["panels"][0]["asset_kind"] = "reference_analysis_board"
    elif mutation == "mismatch-revision":
        _artifact(request, "avp.contract.video-execution-package")["revision"] = "planning-rev-stale"
    elif mutation == "remove-motion-plan":
        request["subject"]["artifacts"] = [
            artifact for artifact in request["subject"]["artifacts"]
            if artifact["artifact_type"] != "avp.contract.shot-motion-plan"
        ]
    elif mutation == "stale-execution-version":
        _artifact(request, "avp.contract.video-execution-package")["schema_version"] = "0.1.0"
    else:
        raise AssertionError(f"Unknown fixture mutation: {mutation}")


if __name__ == "__main__":
    unittest.main()
