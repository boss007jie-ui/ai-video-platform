from __future__ import annotations

import base64
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
from ai_video_platform.skills.storyboard_master_video_planning.sheet_renderer import (
    CAMERA_RED,
    SUBJECT_BLUE,
    _decode_png,
    _draw_in_frame_annotations,
    render_storyboard_sheets,
)


PANEL_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


def color_count(png: bytes, color: tuple[int, int, int, int]) -> int:
    _, _, pixels = _decode_png(png)
    return sum(tuple(pixels[index:index + 4]) == color for index in range(0, len(pixels), 4))


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
        "panel_bytes": {
            "asset://panel/panel-001": PANEL_PNG_B64,
            "asset://panel/panel-002": PANEL_PNG_B64,
        },
        "sheet_render_metadata": {
            "renderer_code_commit": "codex-05-synthetic-commit",
            "font_family": "AVP Bitmap Sans",
            "font_fallback": "monospace",
            "locale": "en-US",
            "render_width": 1200,
            "render_height": 720,
            "panel_visual_observations": {
                "panel-001": {
                    "confidence": 0.95,
                    "objects": [],
                    "contacts": [],
                    "motion_candidates": [],
                },
                "panel-002": {
                    "confidence": 0.95,
                    "objects": [],
                    "contacts": [],
                    "motion_candidates": [],
                },
            },
        },
    }


class VideoPlanningInterfaceTests(unittest.TestCase):
    def test_in_frame_motion_annotations_require_vision_coordinates(self) -> None:
        width, height = 240, 360
        canvas = bytearray(bytes((255, 255, 255, 255)) * width * height)

        _draw_in_frame_annotations(canvas, width, 10, 10, 200, 320, [])

        self.assertEqual(canvas, bytearray(bytes((255, 255, 255, 255)) * width * height))

    def test_in_frame_motion_annotations_follow_visual_coordinates_and_roles(self) -> None:
        width, height = 240, 360
        canvas = bytearray(bytes((255, 255, 255, 255)) * width * height)

        _draw_in_frame_annotations(
            canvas,
            width,
            10,
            10,
            200,
            320,
            [
                {"role": "camera", "points": [[0.1, 0.15], [0.4, 0.35]]},
                {"role": "subject", "points": [[0.85, 0.2], [0.65, 0.45]]},
            ],
        )

        pixels = bytes(canvas)
        self.assertIn(bytes(CAMERA_RED), pixels)
        self.assertIn(bytes(SUBJECT_BLUE), pixels)

    def test_build_storyboard_master_publishes_five_canonical_artifacts(self) -> None:
        result = VideoPlanningInterface().build_storyboard_master(planning_request())

        self.assertEqual(result["schema_version"], "1.0.0")
        artifacts = result["artifacts"]
        self.assertEqual(set(artifacts), {"video_generation_storyboard_master", "shot_motion_plan", "video_execution_package", "first_frame_mapping", "reference_role_mapping"})
        self.assertEqual(artifacts["video_generation_storyboard_master"]["artifact_name"], "VideoGenerationStoryboardMaster")
        self.assertEqual(artifacts["video_generation_storyboard_master"]["contract_id"], "avp.contract.video-generation-storyboard-master")
        sheet_policy = artifacts["video_generation_storyboard_master"]["sheet_outputs"]["execution_policy"]
        self.assertTrue(sheet_policy["provider_execution_input"])
        self.assertEqual(sheet_policy["provider_reference_role"], "storyboard_structure_reference")
        self.assertFalse(sheet_policy["first_frame_eligible"])
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
        self.assertEqual(first["asset_role"], "clean_full_frame_panel")
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
                {"video_generation_storyboard_master.json", "storyboard_master_sheet_001.png", "storyboard_master_sheet_manifest.json", "shot_motion_plan.json", "video_execution_package.json", "first_frame_mapping.json", "reference_role_mapping.json", "video_planning_provenance.json"},
            )
            self.assertGreater((root / "storyboard_master_sheet_001.png").stat().st_size, 0)
            manifest = json.loads((root / "storyboard_master_sheet_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["renderer_version"], "1.4.0")
            self.assertEqual(manifest["layout_version"], "storyboard-master-strip-v3")
            self.assertEqual(manifest["pages"][0]["row_panel_counts"], [2])
            self.assertEqual(
                manifest["execution_policy"]["role"],
                "human_review_and_multimodal_structure_reference",
            )
            self.assertTrue(manifest["execution_policy"]["provider_execution_input"])
            self.assertEqual(
                manifest["execution_policy"]["provider_reference_role"],
                "storyboard_structure_reference",
            )
            self.assertFalse(manifest["execution_policy"]["first_frame_eligible"])

    def test_long_timeline_writes_master_review_sheet_and_segment_execution_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = planning_request()
            for shot in request["production_storyboard_plan"]["shots"]:
                shot["duration_ms"] = 9000
            request["output_root"] = temporary

            result = run_cli("build-storyboard-master", request)

            self.assertTrue(result["ok"])
            root = Path(temporary) / "video_generation_storyboard"
            manifest = json.loads((root / "storyboard_master_sheet_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["execution_policy"]["provider_execution_input"])
            self.assertEqual(
                [segment["segment_id"] for segment in manifest["execution_segments"]],
                ["SEG-001", "SEG-002"],
            )
            self.assertEqual(
                [segment["shot_ids"] for segment in manifest["execution_segments"]],
                [["shot-001"], ["shot-002"]],
            )
            self.assertEqual(
                [segment["panel_ids"] for segment in manifest["execution_segments"]],
                [["panel-001"], ["panel-002"]],
            )
            self.assertEqual(
                [segment["duration_ms"] for segment in manifest["execution_segments"]],
                [9000, 9000],
            )
            segment_paths = [
                page["relative_path"]
                for segment in manifest["execution_segments"]
                for page in segment["pages"]
            ]
            self.assertEqual(
                segment_paths,
                ["storyboard_segment_001_sheet_001.png", "storyboard_segment_002_sheet_001.png"],
            )
            self.assertTrue(all((root / path).is_file() for path in segment_paths))
            self.assertTrue(all(
                segment["execution_policy"]["provider_execution_input"]
                for segment in manifest["execution_segments"]
            ))
            self.assertTrue(all(
                page["execution_policy"]["provider_execution_input"]
                for segment in manifest["execution_segments"]
                for page in segment["pages"]
            ))
            self.assertTrue(all(
                segment["source_master_digest"] == manifest["master_digest"]
                for segment in manifest["execution_segments"]
            ))
            self.assertTrue(all(
                segment["sheet_sha256s"] == [f"sha256:{page['png_sha256']}" for page in segment["pages"]]
                for segment in manifest["execution_segments"]
            ))

    def test_cli_automatically_plans_arrows_from_agent_visual_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            baseline = planning_request()
            baseline["output_root"] = str(Path(temporary) / "baseline")
            self.assertTrue(run_cli("build-storyboard-master", baseline)["ok"])

            request = planning_request()
            request["output_root"] = str(Path(temporary) / "vision-guided")
            request["sheet_render_metadata"]["panel_visual_observations"] = {
                "panel-001": {
                    "confidence": 0.95,
                    "objects": [],
                    "contacts": [],
                    "motion_candidates": [],
                },
                "panel-002": {
                    "confidence": 0.95,
                    "objects": [
                        {"id": "product", "kind": "product", "bbox": [0.25, 0.3, 0.75, 0.8]},
                    ],
                    "contacts": [],
                    "motion_candidates": [
                        {
                            "role": "subject", "action": "rotate", "subject_id": "product",
                            "points": [[0.25, 0.55], [0.35, 0.35], [0.55, 0.3], [0.75, 0.45]],
                            "confidence": 0.93,
                        }
                    ],
                }
            }

            result = run_cli("build-storyboard-master", request)

            self.assertTrue(result["ok"])
            baseline_png = (Path(temporary) / "baseline" / "video_generation_storyboard" / "storyboard_master_sheet_001.png").read_bytes()
            guided_png = (Path(temporary) / "vision-guided" / "video_generation_storyboard" / "storyboard_master_sheet_001.png").read_bytes()
            self.assertGreater(color_count(guided_png, CAMERA_RED), color_count(baseline_png, CAMERA_RED))
            self.assertGreater(color_count(guided_png, SUBJECT_BLUE), color_count(baseline_png, SUBJECT_BLUE))

    def test_renderer_paginates_ten_panels_and_replays_byte_for_byte(self) -> None:
        entries = []
        panel_bytes = {}
        for index in range(10):
            shot = "S01" if index < 3 else f"S{index - 1:02d}"
            panel_id = f"{shot}-P{index + 1:02d}"
            asset_id = f"panel-asset-{index + 1:02d}"
            entries.append(
                {
                    "beat_id": "B01",
                    "shot_id": shot,
                    "panel_id": panel_id,
                    "panel_asset_id": asset_id,
                    "timing_mode": "KEYFRAME_ANCHOR" if index == 0 else "TEMPORAL_SEGMENT",
                    "anchor_time_ms": 0,
                    "anchor_role": "opening" if index == 0 else None,
                    "start_ms": index * 100 if index else None,
                    "end_ms": (index + 1) * 100 if index else None,
                    "duration_ms": 100 if index else None,
                    "camera_motion": {"structured_definition": "locked", "visual_annotation": {"label": "CAMERA", "line_style": "solid"}},
                    "subject_motion": {"structured_definition": "lift", "visual_annotation": {"label": "SUBJECT", "line_style": "dashed"}},
                    "conversion_function": "proof",
                }
            )
            panel_bytes[asset_id] = base64.b64decode(PANEL_PNG_B64)
        master = {"artifact_name": "VideoGenerationStoryboardMaster", "master_panel_entries": entries}
        metadata = {"renderer_code_commit": "test-commit", "render_width": 1200, "render_height": 720}
        first = render_storyboard_sheets(master, panel_bytes, metadata)
        second = render_storyboard_sheets(master, panel_bytes, metadata)
        self.assertEqual(first.pages, second.pages)
        self.assertEqual(len(first.pages), 2)
        self.assertEqual([page["panel_count"] for page in first.manifest["pages"]], [9, 1])
        self.assertEqual([page["row_panel_counts"] for page in first.manifest["pages"]], [[5, 4], [1]])
        self.assertEqual(first.manifest["max_panels_per_page"], 9)
        self.assertEqual(first.manifest["renderer_code_commit"], "test-commit")
        self.assertFalse(first.manifest["execution_policy"]["first_frame_eligible"])
        self.assertTrue(first.manifest["execution_policy"]["provider_execution_input"])
        self.assertIn(b"storyboard-master-strip-v3", first.pages[0])

        seven_panel_strip = render_storyboard_sheets(
            {"artifact_name": "VideoGenerationStoryboardMaster", "master_panel_entries": entries[:7]},
            {key: panel_bytes[key] for key in list(panel_bytes)[:7]},
            metadata,
        )
        self.assertEqual(seven_panel_strip.manifest["pages"][0]["row_panel_counts"], [7])

        vertical_nine = [dict(entry, aspect_ratio="9:16") for entry in entries[:9]]
        vertical_strip = render_storyboard_sheets(
            {"artifact_name": "VideoGenerationStoryboardMaster", "target_aspect_ratio": "9:16", "master_panel_entries": vertical_nine},
            {key: panel_bytes[key] for key in list(panel_bytes)[:9]},
            metadata,
        )
        self.assertEqual(vertical_strip.manifest["pages"][0]["row_panel_counts"], [9])

    def test_renderer_keeps_a_multi_panel_shot_together_at_a_page_break(self) -> None:
        entries = []
        panel_bytes = {}
        for index in range(10):
            shot_id = f"S{index + 1:02d}" if index < 8 else "S09"
            asset_id = f"panel-asset-{index + 1:02d}"
            entries.append(
                {
                    "shot_id": shot_id,
                    "panel_id": f"{shot_id}-P{index + 1:02d}",
                    "panel_asset_id": asset_id,
                    "timing_mode": "TEMPORAL_SEGMENT",
                    "start_ms": index * 100,
                    "end_ms": (index + 1) * 100,
                    "duration_ms": 100,
                    "camera_motion": "locked",
                    "subject_motion": "hand enters frame",
                    "conversion_function": "proof",
                    "aspect_ratio": "9:16",
                }
            )
            panel_bytes[asset_id] = base64.b64decode(PANEL_PNG_B64)

        result = render_storyboard_sheets(
            {"artifact_name": "VideoGenerationStoryboardMaster", "master_panel_entries": entries},
            panel_bytes,
            {"renderer_code_commit": "test-commit", "render_width": 1200, "render_height": 720},
        )

        self.assertEqual([page["panel_count"] for page in result.manifest["pages"]], [8, 2])
        self.assertEqual(result.manifest["pages"][1]["shot_ids"], ["S09"])

    def test_one_shot_can_bind_multiple_selected_panel_assets(self) -> None:
        request = planning_request()
        second = dict(request["production_storyboard_panel_set"]["panels"][1])
        second.update(
            {
                "panel_id": "panel-001-b",
                "panel_asset_id": "asset://panel/panel-001-b",
                "asset_ref": "asset://panel/panel-001-b",
                "panel_sequence": 2,
                "sequence": 3,
            }
        )
        request["production_storyboard_panel_set"]["panels"].append(second)
        request["approved_panel_results"].append({"panel_id": "panel-001-b", "approval_state": "approved"})
        result = VideoPlanningInterface().build_storyboard_master(request)
        entries = result["artifacts"]["video_generation_storyboard_master"]["master_panel_entries"]
        self.assertEqual([entry["panel_id"] for entry in entries[:2]], ["panel-001", "panel-001-b"])
        self.assertEqual([entry["shot_id"] for entry in entries[:2]], ["shot-001", "shot-001"])


if __name__ == "__main__":
    unittest.main()
