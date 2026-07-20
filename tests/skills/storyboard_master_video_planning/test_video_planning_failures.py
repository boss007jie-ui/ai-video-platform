from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
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
from ai_video_platform.skills.storyboard_master_video_planning.cli import main, run_cli
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

    @staticmethod
    def recompute_digest(value: dict[str, object], digest_field: str) -> None:
        body = {key: item for key, item in value.items() if key != digest_field}
        encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        value[digest_field] = "sha256:" + hashlib.sha256(encoded).hexdigest()

    def test_recomputed_digest_cannot_hide_internal_package_contradictions(self) -> None:
        mutations = (
            lambda package: package["source"].__setitem__("storyboard_id", "other-storyboard"),
            lambda package: package.__setitem__("package_id", "vep-forged"),
            lambda package: package["visual_anchors"][0]["anchor"].__setitem__("product_angle", "rear"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                package = self.interface.build_video_plan(planning_request())
                mutate(package)
                self.recompute_digest(package, "package_digest")
                with self.assertRaises(PlanningError) as captured:
                    self.interface.validate_video_plan(package)
                self.assertEqual(captured.exception.code, PlanningErrorCode.PACKAGE_TAMPERED)

    def test_nested_provider_marker_is_rejected_even_with_recomputed_digests(self) -> None:
        package = self.interface.build_video_plan(planning_request())
        package["storyboard_master"]["planning_provider_submission_performed"] = True
        self.recompute_digest(package["storyboard_master"], "master_digest")
        self.recompute_digest(package, "package_digest")
        with self.assertRaises(PlanningError) as captured:
            self.interface.validate_video_plan(package)
        self.assertEqual(captured.exception.code, PlanningErrorCode.PROVIDER_SUBMISSION_FORBIDDEN)

    def test_recomputed_hashes_cannot_hide_nested_identity_or_source_replacement(self) -> None:
        package = self.interface.build_video_plan(planning_request())
        package["storyboard_master"]["contract_status"] = "REGISTERED"
        self.recompute_digest(package["storyboard_master"], "master_digest")
        self.recompute_digest(package, "package_digest")
        with self.assertRaises(PlanningError) as captured:
            self.interface.validate_video_plan(package)
        self.assertEqual(captured.exception.code, PlanningErrorCode.PACKAGE_TAMPERED)

        package = self.interface.build_video_plan(planning_request())
        package["source"] = {}
        package["storyboard_master"]["source"] = {}
        empty_digest = hashlib.sha256(b"{}").hexdigest()
        package["package_id"] = "vep-" + empty_digest[:20]
        self.recompute_digest(package["storyboard_master"], "master_digest")
        self.recompute_digest(package, "package_digest")
        with self.assertRaises(PlanningError) as captured:
            self.interface.validate_video_plan(package)
        self.assertEqual(captured.exception.code, PlanningErrorCode.PACKAGE_INVALID)

    def test_recomputed_hashes_cannot_hide_malformed_mapping(self) -> None:
        package = self.interface.build_video_plan(planning_request())
        malformed = [{"shot_id": "", "role": "hero", "asset_id": "asset", "uri": "memory://x", "sha256": "sha256:" + "a" * 64}]
        package["asset_mapping"] = malformed
        package["storyboard_master"]["asset_mapping"] = malformed
        self.recompute_digest(package["storyboard_master"], "master_digest")
        self.recompute_digest(package, "package_digest")
        with self.assertRaises(PlanningError) as captured:
            self.interface.validate_video_plan(package)
        self.assertEqual(captured.exception.code, PlanningErrorCode.PACKAGE_INVALID)

    def test_shot_without_required_assets_is_rejected_before_build(self) -> None:
        request = planning_request()
        request["storyboard"]["shots"][0]["required_asset_roles"] = []
        self.assert_code(request, PlanningErrorCode.INVALID_INPUT)

    def test_blank_role_and_non_hex_asset_digest_are_rejected(self) -> None:
        request = planning_request()
        request["storyboard"]["shots"][0]["required_asset_roles"] = ["   "]
        self.assert_code(request, PlanningErrorCode.INVALID_INPUT)

        request = planning_request()
        request["asset_manifest"]["assets"][0]["sha256"] = "sha256:" + "z" * 64
        self.assert_code(request, PlanningErrorCode.INVALID_INPUT)

    def test_cli_returns_stable_error(self) -> None:
        request = planning_request()
        request["asset_manifest"]["assets"] = []
        result = run_cli("build-video-plan", request)
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "ASSET_MAPPING_MISSING")

    def test_module_cli_argument_error_is_machine_readable(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main([])
        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
