from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_generation import GenerationError, GenerationErrorCode, VideoGenerationInterface
from tests.skills.video_generation.test_video_generation_interface import NOW, generation_request


class CountingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def submit(self, request: object) -> str:
        self.calls += 1
        return "should-not-run"


class CountingLedger:
    def __init__(self) -> None:
        self.calls = 0

    def reserve(self, *args: object, **kwargs: object) -> tuple[dict[str, object], bool]:
        self.calls += 1
        return {}, False


class VideoGenerationSafetyTests(unittest.TestCase):
    def assert_code(self, request: dict[str, object], code: GenerationErrorCode) -> None:
        adapter, ledger = CountingAdapter(), CountingLedger()
        with self.assertRaises(GenerationError) as captured:
            VideoGenerationInterface(adapter=adapter, ledger=ledger).submit_video(request, now=NOW)
        self.assertEqual(captured.exception.code, code)
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(ledger.calls, 0)

    def test_legacy_draft_or_unsupported_version_is_rejected_before_provider(self) -> None:
        request = generation_request()
        request["execution_package"]["schema_version"] = "0.1.0"
        self.assert_code(request, GenerationErrorCode.PACKAGE_VERSION_UNSUPPORTED)
        request = generation_request()
        request["execution_package"]["video_generation_storyboard_master"]["artifact_name"] = "StoryboardMaster"
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

    def test_revision_and_order_divergence_is_rejected_before_provider(self) -> None:
        request = generation_request()
        request["execution_package"]["shot_motion_plan"]["planning_revision"] = "other"
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)
        request = generation_request()
        request["execution_package"]["panel_order"].reverse()
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

    def test_unapproved_panel_or_forbidden_first_frame_is_rejected_before_provider(self) -> None:
        request = generation_request()
        request["execution_package"]["asset_mapping"][0]["approval_state"] = "pending"
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)
        request = generation_request()
        first = request["execution_package"]["first_frame_mapping"]
        first["asset_ref"] = "asset://production-panels/storyboard_contact_sheet"
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

    def test_analysis_board_may_not_be_provider_input_or_first_frame(self) -> None:
        request = generation_request()
        references = request["execution_package"]["reference_role_mapping"]["references"]
        board = next(item for item in references if item["role"] == "global_structure_reference")
        board["provider_execution_input"] = True
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

    def test_duplicate_panel_stale_artifact_ref_or_motion_divergence_fails_closed(self) -> None:
        request = generation_request()
        request["execution_package"]["asset_mapping"].append(deepcopy(request["execution_package"]["asset_mapping"][0]))
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

        request = generation_request()
        request["execution_package"]["video_generation_storyboard_master"]["first_frame_mapping_ref"] = "sha256:" + "0" * 64
        self.assert_code(request, GenerationErrorCode.PACKAGE_TAMPERED)

        request = generation_request()
        request["execution_package"]["shot_motion_plan"]["shots"][0]["camera_motion"] = "different"
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

    def test_duplicate_provider_reference_mapping_fails_closed(self) -> None:
        request = generation_request()
        mapping = next(item for item in request["execution_package"]["asset_mapping"] if item["role"] == "character_reference")
        request["execution_package"]["asset_mapping"].append(deepcopy(mapping))
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

    def test_generation_source_has_no_private_planning_import(self) -> None:
        root = SOURCE_ROOT / "ai_video_platform" / "skills" / "video_generation"
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn("storyboard_master_video_planning", node.module, path)
                if isinstance(node, ast.Import):
                    self.assertTrue(all("storyboard_master_video_planning" not in item.name for item in node.names), path)


if __name__ == "__main__":
    unittest.main()
