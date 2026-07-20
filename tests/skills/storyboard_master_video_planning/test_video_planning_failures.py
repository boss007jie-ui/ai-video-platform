from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.storyboard_master_video_planning import (
    PlanningError,
    PlanningErrorCode,
    VideoPlanningInterface,
)
from ai_video_platform.skills.storyboard_master_video_planning.cli import run_cli
from tests.skills.storyboard_master_video_planning.test_video_planning_interface import planning_request


class VideoPlanningFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.interface = VideoPlanningInterface()

    def assert_code(self, request: dict[str, object], code: PlanningErrorCode) -> None:
        with self.assertRaises(PlanningError) as captured:
            self.interface.build_video_plan(request)
        self.assertEqual(captured.exception.code, code)

    def test_missing_asset_fails_closed(self) -> None:
        request = planning_request()
        request["asset_manifest"]["assets"] = []
        self.assert_code(request, PlanningErrorCode.ASSET_MAPPING_MISSING)

    def test_unapproved_asset_fails_closed(self) -> None:
        request = planning_request()
        request["asset_manifest"]["assets"][0]["approval_state"] = "pending"
        self.assert_code(request, PlanningErrorCode.ASSET_NOT_APPROVED)

    def test_partial_mapping_fails_closed(self) -> None:
        request = planning_request()
        request["asset_manifest"]["assets"][0]["shot_ids"] = ["shot-001"]
        self.assert_code(request, PlanningErrorCode.ASSET_MAPPING_MISSING)

    def test_ambiguous_mapping_fails_closed(self) -> None:
        request = planning_request()
        duplicate = deepcopy(request["asset_manifest"]["assets"][0])
        duplicate["asset_id"] = "asset-duplicate"
        request["asset_manifest"]["assets"].append(duplicate)
        self.assert_code(request, PlanningErrorCode.ASSET_MAPPING_AMBIGUOUS)

    def test_stale_storyboard_or_manifest_fails_closed(self) -> None:
        for field in ("expected_storyboard_revision", "expected_asset_manifest_revision"):
            with self.subTest(field=field):
                request = planning_request()
                request[field] = 99
                self.assert_code(request, PlanningErrorCode.STALE_INPUT_VERSION)

    def test_continuity_conflict_fails_closed(self) -> None:
        request = planning_request()
        request["storyboard"]["shots"][1]["visual_anchor"] = {"product_angle": "rear"}
        self.assert_code(request, PlanningErrorCode.CONTINUITY_CONFLICT)

    def test_duplicate_shot_sequence_fails_closed(self) -> None:
        request = planning_request()
        request["storyboard"]["shots"][1]["sequence"] = 2
        self.assert_code(request, PlanningErrorCode.SHOT_SEQUENCE_INVALID)

    def test_tampered_package_is_rejected(self) -> None:
        package = self.interface.build_video_plan(planning_request())
        package["motion_plan"][0]["motion"]["kind"] = "tampered"
        with self.assertRaises(PlanningError) as captured:
            self.interface.validate_video_plan(package)
        self.assertEqual(captured.exception.code, PlanningErrorCode.PACKAGE_TAMPERED)

    def test_provider_submission_marker_is_rejected(self) -> None:
        package = self.interface.build_video_plan(planning_request())
        package["planning_provider_submission_performed"] = True
        with self.assertRaises(PlanningError) as captured:
            self.interface.validate_video_plan(package)
        self.assertEqual(captured.exception.code, PlanningErrorCode.PROVIDER_SUBMISSION_FORBIDDEN)

    def test_cli_returns_stable_error(self) -> None:
        request = planning_request()
        request["asset_manifest"]["assets"] = []
        result = run_cli("build-video-plan", request)
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "ASSET_MAPPING_MISSING")


if __name__ == "__main__":
    unittest.main()
