from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.storyboard_master_video_planning import PlanningError, PlanningErrorCode, VideoPlanningInterface
from ai_video_platform.skills.storyboard_master_video_planning.cli import run_cli
from tests.skills.storyboard_master_video_planning.test_video_planning_interface import planning_request


class VideoPlanningFailureTests(unittest.TestCase):
    def assert_code(self, request: dict[str, object], code: PlanningErrorCode) -> None:
        with self.assertRaises(PlanningError) as captured:
            VideoPlanningInterface().build_storyboard_master(request)
        self.assertEqual(captured.exception.code, code)

    def test_unapproved_or_missing_panel_fails_closed(self) -> None:
        request = planning_request()
        request["production_storyboard_panel_set"]["panels"][0]["approval_state"] = "pending"
        self.assert_code(request, PlanningErrorCode.ASSET_NOT_APPROVED)
        request = planning_request()
        request["production_storyboard_panel_set"]["panels"].pop()
        self.assert_code(request, PlanningErrorCode.ASSET_MAPPING_MISSING)

    def test_non_selected_duplicate_asset_and_orphan_panel_fail_closed(self) -> None:
        request = planning_request()
        request["production_storyboard_panel_set"]["panels"][0]["usage_status"] = "SUPERSEDED"
        self.assert_code(request, PlanningErrorCode.ASSET_NOT_APPROVED)

        request = planning_request()
        request["production_storyboard_panel_set"]["panels"][0]["asset_ref"] = request["production_storyboard_panel_set"]["panels"][1]["asset_ref"]
        self.assert_code(request, PlanningErrorCode.ASSET_MAPPING_AMBIGUOUS)

        request = planning_request()
        request["production_storyboard_panel_set"]["panels"][0]["shot_id"] = "shot-orphan"
        self.assert_code(request, PlanningErrorCode.ASSET_MAPPING_MISSING)

    def test_revision_product_or_order_divergence_fails_closed(self) -> None:
        mutations = (
            lambda request: request["production_storyboard_panel_set"].__setitem__("planning_revision", "other"),
            lambda request: request["product_context_bundle"].__setitem__("product_id", "other"),
            lambda request: request["production_storyboard_panel_set"]["panels"][0].__setitem__("sequence", 1),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                request = planning_request()
                mutation(request)
                self.assert_code(request, PlanningErrorCode.STALE_INPUT_VERSION)

    def test_contact_sheet_analysis_board_or_dirty_panel_cannot_be_first_frame(self) -> None:
        for field, value in (("asset_ref", "asset://production-panels/storyboard_contact_sheet"), ("contains_label", True), ("clean_full_frame", False)):
            with self.subTest(field=field):
                request = planning_request()
                request["production_storyboard_panel_set"]["panels"][1][field] = value
                self.assert_code(request, PlanningErrorCode.FIRST_FRAME_INELIGIBLE)

    def test_analysis_board_role_cannot_be_overridden_into_provider_input(self) -> None:
        request = planning_request()
        request["reference_analysis_board_manifest"]["assets"][0]["provider_execution_input"] = True
        self.assert_code(request, PlanningErrorCode.REFERENCE_ROLE_FORBIDDEN)

    def test_duplicate_reference_mapping_fails_closed(self) -> None:
        request = planning_request()
        request["reference_assets"].append(deepcopy(request["reference_assets"][0]))
        self.assert_code(request, PlanningErrorCode.ASSET_MAPPING_AMBIGUOUS)

    def test_planning_is_deterministic_and_never_calls_provider(self) -> None:
        request = planning_request()
        first = VideoPlanningInterface().build_storyboard_master(request)
        second = VideoPlanningInterface().build_storyboard_master(deepcopy(request))
        self.assertEqual(first, second)
        self.assertFalse(first["planning_provider_submission_performed"])

    def test_empty_duplicate_or_gapped_shot_order_and_bad_reference_digest_fail_closed(self) -> None:
        request = planning_request()
        request["production_storyboard_plan"]["shots"] = []
        request["production_storyboard_panel_set"]["panels"] = []
        self.assert_code(request, PlanningErrorCode.INVALID_SHOT_ORDER)

        for sequences in ((1, 1), (1, 3)):
            request = planning_request()
            request["production_storyboard_plan"]["shots"][0]["sequence"] = sequences[1]
            request["production_storyboard_plan"]["shots"][1]["sequence"] = sequences[0]
            self.assert_code(request, PlanningErrorCode.INVALID_SHOT_ORDER)

        request = planning_request()
        request["reference_assets"][0]["sha256"] = "not-a-digest"
        self.assert_code(request, PlanningErrorCode.INVALID_INPUT)

    def test_cli_rejects_invalid_visual_observations_before_writing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = planning_request()
            request["output_root"] = temporary
            request["sheet_render_metadata"]["panel_visual_observations"] = {
                "panel-002": {
                    "confidence": 0.95,
                    "objects": [
                        {"id": "product", "kind": "product", "bbox": [0.25, 0.3, 1.2, 0.8]},
                    ],
                    "contacts": [],
                    "motion_candidates": [],
                }
            }

            result = run_cli("build-storyboard-master", request)

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], PlanningErrorCode.INVALID_INPUT.value)
            self.assertFalse((Path(temporary) / "video_generation_storyboard").exists())


if __name__ == "__main__":
    unittest.main()
