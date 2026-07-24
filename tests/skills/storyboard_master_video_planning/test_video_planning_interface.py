from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.storyboard_master_video_planning import VideoPlanningInterface
from ai_video_platform.skills.storyboard_master_video_planning.cli import run_cli


def planning_request() -> dict[str, object]:
    digest = "sha256:" + "a" * 64
    return {
        "production_storyboard_plan": {
            "artifact_name": "ProductionStoryboardPlan",
            "contract_id": "avp.contract.production-storyboard-plan",
            "schema_version": "1.0.0",
            "planning_revision": "plan-rev-003",
            "product_id": "product-001",
            "target_aspect_ratio": "9:16",
            "shots": [
                {
                    "shot_id": "shot-002", "sequence": 2, "duration_ms": 2200,
                    "start_state": "product held at chest height", "middle_state": "product rotates toward camera",
                    "end_state": "product label faces camera", "motion_path": "clockwise quarter turn",
                    "character_state": "presenter steady", "product_state": "label revealed", "emotion": "confident",
                    "camera_motion": "slow push-in", "transition": "cut", "voiceover": "See every detail.",
                    "caption": "Exact product", "sound_effect": "soft whoosh", "cta": "Shop now",
                },
                {
                    "shot_id": "shot-001", "sequence": 1, "duration_ms": 1800,
                    "start_state": "clean hero frame", "middle_state": "light sweeps across product",
                    "end_state": "product remains centered", "motion_path": "static hold",
                    "character_state": "no character", "product_state": "front view", "emotion": "curious",
                    "camera_motion": "locked", "transition": "fade-in", "voiceover": "Meet the product.",
                    "caption": "New arrival", "sound_effect": "soft chime", "cta": "",
                },
            ],
        },
        "production_storyboard_panel_set": {
            "artifact_name": "ProductionStoryboardPanelSet",
            "contract_id": "avp.contract.production-storyboard-panel-set",
            "schema_version": "1.0.0",
            "planning_revision": "plan-rev-003",
            "product_id": "product-001",
            "panels": [
                {"panel_id": "panel-002", "shot_id": "shot-002", "sequence": 2, "asset_ref": "asset://panel/panel-002", "sha256": digest, "approval_state": "approved", "approval_ref": "approval://panel-002", "aspect_ratio": "9:16", "clean_full_frame": True, "contains_grid": False, "contains_number": False, "contains_label": False, "contains_caption": False, "contains_other_shot": False},
                {"panel_id": "panel-001", "shot_id": "shot-001", "sequence": 1, "asset_ref": "asset://panel/panel-001", "sha256": digest, "approval_state": "approved", "approval_ref": "approval://panel-001", "aspect_ratio": "9:16", "clean_full_frame": True, "contains_grid": False, "contains_number": False, "contains_label": False, "contains_caption": False, "contains_other_shot": False},
            ],
        },
        "product_context_bundle": {"bundle_id": "product-context-001", "product_id": "product-001", "revision": 4},
        "approved_panel_results": [
            {"panel_id": "panel-001", "approval_state": "approved"},
            {"panel_id": "panel-002", "approval_state": "approved"},
        ],
        "reference_assets": [
            {"asset_ref": "asset://reference/character-001", "sha256": "sha256:" + "b" * 64, "role": "character_reference", "approval_state": "approved"}
        ],
        "reference_analysis_board_manifest": {
            "artifact_name": "ReferenceAnalysisBoardManifest", "schema_version": "1.0.0",
            "assets": [{"asset_ref": "asset://reference-analysis/board-001", "kind": "reference_analysis_board"}],
        },
    }


class VideoPlanningInterfaceTests(unittest.TestCase):
    def test_build_storyboard_master_publishes_five_canonical_artifacts(self) -> None:
        result = VideoPlanningInterface().build_storyboard_master(planning_request())

        self.assertEqual(result["schema_version"], "1.0.0")
        artifacts = result["artifacts"]
        self.assertEqual(set(artifacts), {"video_generation_storyboard_master", "shot_motion_plan", "video_execution_package", "first_frame_mapping", "reference_role_mapping"})
        self.assertEqual(artifacts["video_generation_storyboard_master"]["artifact_name"], "VideoGenerationStoryboardMaster")
        self.assertEqual(artifacts["video_generation_storyboard_master"]["contract_id"], "avp.contract.video-generation-storyboard-master")
        self.assertEqual(artifacts["video_execution_package"]["schema_version"], "1.0.0")
        artifact_names = {item["artifact_name"] for item in artifacts.values()}
        self.assertNotIn("StoryboardMaster", artifact_names)
        self.assertFalse(result["planning_provider_submission_performed"])

    def test_master_is_complete_ordered_and_uses_clean_real_first_frame(self) -> None:
        artifacts = VideoPlanningInterface().build_storyboard_master(planning_request())["artifacts"]
        master = artifacts["video_generation_storyboard_master"]
        self.assertEqual([shot["shot_id"] for shot in master["shots"]], ["shot-001", "shot-002"])
        required = {"duration_ms", "start_state", "middle_state", "end_state", "motion_path", "character_state", "product_state", "emotion", "camera_motion", "transition", "voiceover", "caption", "sound_effect", "cta", "panel_id", "panel_asset_ref"}
        self.assertTrue(all(required <= set(shot) for shot in master["shots"]))
        first = artifacts["first_frame_mapping"]
        self.assertEqual(first["shot_id"], "shot-001")
        self.assertEqual(first["panel_id"], "panel-001")
        self.assertEqual(first["asset_ref"], "asset://panel/panel-001")
        self.assertTrue(first["clean_full_frame"])
        self.assertFalse(any(first[field] for field in ("contains_grid", "contains_number", "contains_label", "contains_caption", "contains_other_shot")))

    def test_reference_roles_are_explicit_and_analysis_board_is_structural_only(self) -> None:
        roles = VideoPlanningInterface().build_storyboard_master(planning_request())["artifacts"]["reference_role_mapping"]["references"]
        by_ref = {item["asset_ref"]: item for item in roles}
        self.assertEqual(by_ref["asset://reference/character-001"]["role"], "character_reference")
        board = by_ref["asset://reference-analysis/board-001"]
        self.assertEqual(board["role"], "global_structure_reference")
        self.assertFalse(board["provider_execution_input"])
        self.assertFalse(board["first_frame_eligible"])

    def test_cli_writes_the_frozen_output_tree_without_provider_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = planning_request()
            request["output_root"] = temporary
            result = run_cli("build-storyboard-master", request)
            self.assertTrue(result["ok"])
            root = Path(temporary) / "video_generation_storyboard"
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {"video_generation_storyboard_master.json", "video_storyboard_master.png", "shot_motion_plan.json", "video_execution_package.json", "first_frame_mapping.json", "reference_role_mapping.json", "video_planning_provenance.json"},
            )
            self.assertGreater((root / "video_storyboard_master.png").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
