from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.contracts.serialization import thaw_json
from ai_video_platform.skills.product_image_panel_generation import (
    FakeImageProviderAdapter,
    FakeProviderStep,
    GenerationItem,
    ImagePanelError,
    ImagePanelErrorCode,
    ProductionStoryboardPanelService,
    calculate_model_profile_digest,
    generation_request_to_mapping,
    model_profile_to_mapping,
    storyboard_panel_request_from_mapping,
)
from ai_video_platform.skills.product_image_panel_generation.cli import main as cli_main

from ._support import NOW_TEXT, PRODUCT_ID, TASK_ID, _envelope, make_request, profile, rebind_request


FIXTURE_ROOT = Path(__file__).with_name("fixtures")
PANEL_PLAN_PATH = FIXTURE_ROOT / "production-storyboard-panel-plan-v1.json"
ASSET_FIXTURE_PATH = FIXTURE_ROOT / "approved-storyboard-assets-v1.json"
REQUIRED_OUTPUTS = {
    "panel_plan.json",
    "panel_prompts.json",
    "panel_images",
    "storyboard_contact_sheet.png",
    "production_storyboard_panel_set.json",
    "panel_qa_report.json",
    "panel_generation_provenance.json",
}


def _fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _storyboard_document() -> dict:
    panel_plan = _fixture(PANEL_PLAN_PATH)
    assets_fixture = _fixture(ASSET_FIXTURE_PATH)
    approved_assets = assets_fixture["approved_assets"]
    asset_ids = tuple(asset["asset_id"] for asset in approved_assets)
    product_context = _envelope(
        "avp.contract.product-context-bundle",
        {
            "bundle_id": "bundle-storyboard-panels-synthetic-v1",
            "bundle_revision": 1,
            "product_id": PRODUCT_ID,
            "purpose": "product-image-panel-generation",
            "facts": [
                {
                    "fact_id": "fact-product-identity-004",
                    "field": "visual_identity",
                    "value": "matte blue bottle with white wordmark",
                    "provenance": {"source": "synthetic-approved-fixture"},
                }
            ],
            "approved_asset_refs": list(asset_ids),
            "rule_refs": [],
            "known_error_refs": [],
            "successful_pattern_refs": [],
            "source_evidence": ["evidence-storyboard-panels-synthetic-v1"],
            "generated_at": NOW_TEXT,
            "visual_constraints": {"required_color": "matte blue", "logo_visibility": "front"},
            "packaging": {"state": "retail-box-closed"},
            "dimensions": {"height_mm": 220, "width_mm": 70},
        },
        "product-knowledge",
        "skill",
    )
    asset_manifest = _envelope(
        "avp.contract.asset-manifest",
        {
            "manifest_id": "asset-manifest-storyboard-panels-synthetic-v1",
            "manifest_revision": 1,
            "owner_type": "product",
            "owner_id": PRODUCT_ID,
            "assets": [
                {
                    "asset_id": asset["asset_id"],
                    "role": asset["role"],
                    "artifact_type": asset["artifact_type"],
                    "media_type": "image",
                    "uri": asset["uri"],
                    "sha256": asset["sha256"],
                    "byte_size": 64,
                    "provenance": {"source": "synthetic-approved-fixture"},
                    "created_at": NOW_TEXT,
                    "approval_ref": f"approval://asset/{asset['asset_id']}",
                }
                for asset in approved_assets
            ],
            "created_at": NOW_TEXT,
        },
        "product-knowledge",
        "skill",
    )
    base = make_request(
        approved_assets=asset_ids,
        input_asset_ids=asset_ids,
        width=576,
        height=1024,
    )
    items = tuple(
        GenerationItem(
            item_id=panel["panel_id"],
            role="production-storyboard-panel",
            prompt=panel["prompt"],
            width=panel["width"],
            height=panel["height"],
            input_asset_ids=tuple(panel["approved_asset_ids"]),
        )
        for panel in panel_plan["panels"]
    )
    request = rebind_request(
        base,
        request_id="production-storyboard-panels-synthetic-v1",
        idempotency_key="production-storyboard-panels-synthetic-v1",
        product_context=product_context,
        input_asset_manifests=(asset_manifest,),
        items=items,
    )
    return {
        "panel_plan": panel_plan,
        "anchor_set": assets_fixture["anchor_set"],
        "request": generation_request_to_mapping(request),
        "model_profile": model_profile_to_mapping(profile()),
    }


def _service(adapter: FakeImageProviderAdapter) -> ProductionStoryboardPanelService:
    return ProductionStoryboardPanelService(
        provider=adapter,
        profiles=(profile(),),
        now=lambda: datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
        sleep=lambda _seconds: None,
    )


class StoryboardPanelArtifactTests(unittest.TestCase):
    def test_generate_panels_cli_writes_canonical_artifact_chain(self) -> None:
        document = _storyboard_document()
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            input_path = workspace / "generate-panels.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            exit_code = cli_main(
                ["generate-panels", "--input", str(input_path), "--adapter", "fake"],
                stdout=output,
            )

            payload = json.loads(output.getvalue())
            output_root = workspace / "production_storyboard_panels"
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["provider_smoke"], "NOT_REQUIRED")
            self.assertEqual({path.name for path in output_root.iterdir()}, REQUIRED_OUTPUTS)

            panel_set = json.loads((output_root / "production_storyboard_panel_set.json").read_text(encoding="utf-8"))
            prompts = json.loads((output_root / "panel_prompts.json").read_text(encoding="utf-8"))
            qa_report = json.loads((output_root / "panel_qa_report.json").read_text(encoding="utf-8"))
            provenance = json.loads((output_root / "panel_generation_provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(panel_set["artifact_type"], "ProductionStoryboardPanelSet")
            self.assertEqual(panel_set["contract_id"], "avp.contract.production-storyboard-panel-set")
            self.assertEqual(panel_set["schema_version"], "1.0.0")
            self.assertEqual(panel_set["contract_status"], "IDENTITY_REGISTERED_SCHEMA_PENDING")
            self.assertEqual([panel["panel_id"] for panel in panel_set["panels"]], ["panel-001", "panel-002"])
            self.assertEqual([panel["shot_id"] for panel in panel_set["panels"]], ["shot-001", "shot-002"])
            self.assertTrue(all(panel["usage_status"] == "SELECTED" for panel in panel_set["panels"]))
            self.assertTrue(all(panel["panel_asset_facts"]["panel_asset_id"] == panel["asset"]["asset_id"] for panel in panel_set["panels"]))
            self.assertTrue(all(panel["plan_binding_summary"]["panel_id"] == panel["panel_id"] for panel in panel_set["panels"]))
            self.assertTrue(all(panel["approval_evidence"]["kind"] == "ApprovalRecord" for panel in panel_set["panels"]))
            self.assertTrue(all(panel["approval_evidence"]["panel_asset_id"] == panel["panel_asset_facts"]["panel_asset_id"] for panel in panel_set["panels"]))
            self.assertTrue(all(panel["approval_evidence"]["asset_sha256"] == panel["panel_asset_facts"]["sha256"] for panel in panel_set["panels"]))
            self.assertEqual(qa_report["overall_status"], "pass")
            self.assertEqual(qa_report["set_checks"]["panel_plan_coverage"], "pass")
            self.assertEqual(qa_report["set_checks"]["cross_panel_continuity"], "pass")
            self.assertTrue(all(panel["qa_status"] == "pass" for panel in panel_set["panels"]))
            self.assertTrue(all(prompt["request_hash"] == document["request"]["request_hash"] for prompt in prompts["panels"]))
            self.assertEqual(provenance["provider_network_performed"], False)
            self.assertEqual(provenance["provider_state"], "RC_PROVIDER_PENDING / NOT_AUTHORIZED")

            for panel in panel_set["panels"]:
                image_path = output_root / panel["asset"]["relative_path"]
                content = image_path.read_bytes()
                self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual(hashlib.sha256(content).hexdigest(), panel["asset"]["sha256"])
                self.assertEqual(panel["asset"]["dimensions"], {"height": 1024, "width": 576})
                self.assertEqual(len(panel["approved_source_asset_ids"]), 6)

            contact_sheet = panel_set["contact_sheet"]
            self.assertEqual(contact_sheet["role"], "human_review_only")
            self.assertFalse(contact_sheet["individual_panel"])
            self.assertFalse(contact_sheet["first_frame_eligible"])
            self.assertFalse(contact_sheet["provider_execution_input"])
            self.assertTrue((output_root / "storyboard_contact_sheet.png").read_bytes().startswith(b"\x89PNG"))

    def test_identity_anchor_and_plan_coverage_rejections_precede_provider(self) -> None:
        cases = []
        wrong_identity = _storyboard_document()
        wrong_identity["panel_plan"]["contract_id"] = "avp.contract.reference-storyboard-analysis"
        cases.append((wrong_identity, ImagePanelErrorCode.PANEL_PLAN_INVALID))

        wrong_anchor = _storyboard_document()
        wrong_anchor["anchor_set"]["product_id"] = "other-product"
        cases.append((wrong_anchor, ImagePanelErrorCode.ANCHOR_MISMATCH))

        missing_coverage = _storyboard_document()
        request = storyboard_panel_request_from_mapping(missing_coverage).generation_request
        changed = rebind_request(request, items=request.items[:1])
        missing_coverage["request"] = generation_request_to_mapping(changed)
        cases.append((missing_coverage, ImagePanelErrorCode.PANEL_PLAN_COVERAGE_INVALID))

        for document, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                adapter = FakeImageProviderAdapter()
                with tempfile.TemporaryDirectory() as directory:
                    output_root = Path(directory) / "production_storyboard_panels"
                    with self.assertRaises(ImagePanelError) as captured:
                        _service(adapter).generate_panels(
                            storyboard_panel_request_from_mapping(document),
                            output_root=output_root,
                        )
                    self.assertFalse(output_root.exists())
                self.assertEqual(captured.exception.code, expected_code)
                self.assertEqual(adapter.total_attempts, 0)

    def test_reference_analysis_board_is_rejected_as_provider_input(self) -> None:
        document = _storyboard_document()
        request = storyboard_panel_request_from_mapping(document).generation_request
        manifest_payload = thaw_json(request.input_asset_manifests[0].payload)
        manifest_payload["assets"][0]["role"] = "ReferenceStoryboardAnalysisBoard"
        manifest = _envelope(
            "avp.contract.asset-manifest",
            manifest_payload,
            "product-knowledge",
            "skill",
        )
        changed = rebind_request(request, input_asset_manifests=(manifest,))
        document["request"] = generation_request_to_mapping(changed)
        adapter = FakeImageProviderAdapter()

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ImagePanelError) as captured:
                _service(adapter).generate_panels(
                    storyboard_panel_request_from_mapping(document),
                    output_root=Path(directory) / "production_storyboard_panels",
                )

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.REFERENCE_BOARD_MISUSE)
        self.assertEqual(adapter.total_attempts, 0)

    def test_scale_and_undeclared_continuity_changes_fail_before_provider(self) -> None:
        scale_document = _storyboard_document()
        scale_document["panel_plan"]["panels"][1]["continuity"]["relative_scale"]["packaging_to_product"] = 9.0
        continuity_document = _storyboard_document()
        continuity_document["panel_plan"]["panels"][1]["continuity"]["wardrobe_anchor_id"] = "wardrobe-unapproved"

        for document in (scale_document, continuity_document):
            adapter = FakeImageProviderAdapter()
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ImagePanelError) as captured:
                    _service(adapter).generate_panels(
                        storyboard_panel_request_from_mapping(document),
                        output_root=Path(directory) / "production_storyboard_panels",
                    )
            self.assertEqual(captured.exception.code, ImagePanelErrorCode.CONTINUITY_INVALID)
            self.assertEqual(adapter.total_attempts, 0)

    def test_partial_failure_preserves_plan_coverage_and_per_panel_qa(self) -> None:
        adapter = FakeImageProviderAdapter(
            script={"panel-002": [FakeProviderStep.failure("synthetic failure", retryable=False)]}
        )
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "production_storyboard_panels"
            outcome = _service(adapter).generate_panels(
                storyboard_panel_request_from_mapping(_storyboard_document()),
                output_root=output_root,
            )
            panel_set = json.loads((output_root / "production_storyboard_panel_set.json").read_text(encoding="utf-8"))
            qa_report = json.loads((output_root / "panel_qa_report.json").read_text(encoding="utf-8"))

            self.assertEqual(outcome.status.value, "partial_failure")
            self.assertEqual([panel["generation_status"] for panel in panel_set["panels"]], ["completed"])
            self.assertEqual([panel["qa_status"] for panel in panel_set["panels"]], ["pass"])
            self.assertEqual(qa_report["overall_status"], "fail")
            self.assertEqual(qa_report["set_checks"]["panel_plan_coverage"], "pass")
            self.assertTrue((output_root / "panel_images" / "panel-001.png").is_file())
            self.assertFalse((output_root / "panel_images" / "panel-002.png").exists())
            self.assertEqual(qa_report["panels"][1]["qa_status"], "failed_generation")

    def test_generate_panels_cli_rejecting_adapter_writes_non_network_failure_artifacts(self) -> None:
        document = _storyboard_document()
        rejecting_profile = replace(profile(), provider_id="rejecting")
        request = storyboard_panel_request_from_mapping(document).generation_request
        document["request"] = generation_request_to_mapping(
            rebind_request(
                request,
                model_profile_digest=calculate_model_profile_digest(rejecting_profile),
            )
        )
        document["model_profile"] = model_profile_to_mapping(rejecting_profile)
        output = StringIO()

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            input_path = workspace / "generate-panels.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            exit_code = cli_main(
                ["generate-panels", "--input", str(input_path), "--adapter", "rejecting"],
                stdout=output,
            )

            payload = json.loads(output.getvalue())
            output_root = workspace / "production_storyboard_panels"
            panel_set = json.loads((output_root / "production_storyboard_panel_set.json").read_text(encoding="utf-8"))
            provenance = json.loads((output_root / "panel_generation_provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 3)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["provider_smoke"], "NOT_REQUIRED")
            self.assertEqual(panel_set["status"], "failed")
            self.assertEqual(panel_set["panels"], [])
            self.assertFalse(provenance["provider_network_performed"])

    def test_non_selected_usage_status_is_rejected_before_provider(self) -> None:
        for status in ("ALTERNATE", "FAILED", "DISCARDED", "SUPERSEDED"):
            document = _storyboard_document()
            document["panel_plan"]["panels"][0]["usage_status"] = status
            adapter = FakeImageProviderAdapter()
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ImagePanelError) as captured:
                    _service(adapter).generate_panels(
                        storyboard_panel_request_from_mapping(document),
                        output_root=Path(directory) / "production_storyboard_panels",
                    )
            self.assertEqual(captured.exception.code, ImagePanelErrorCode.PANEL_USAGE_INVALID)
            self.assertEqual(adapter.total_attempts, 0)

    def test_selected_panel_requires_current_approval_evidence(self) -> None:
        document = _storyboard_document()
        request = storyboard_panel_request_from_mapping(document).generation_request
        request = replace(request, approval_record=None)
        document["request"] = generation_request_to_mapping(request)
        adapter = FakeImageProviderAdapter()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ImagePanelError) as captured:
                _service(adapter).generate_panels(
                    storyboard_panel_request_from_mapping(document),
                    output_root=Path(directory) / "production_storyboard_panels",
                )
        self.assertEqual(captured.exception.code, ImagePanelErrorCode.APPROVAL_REQUIRED)
        self.assertEqual(adapter.total_attempts, 0)


if __name__ == "__main__":
    unittest.main()
