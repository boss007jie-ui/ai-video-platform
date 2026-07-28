from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.orchestration.project_copy import inspect_project


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _tree_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _project_fixture(root: Path) -> None:
    plan = {
        "task_id": "old-task-001",
        "artifact_id": "old-storyboard-plan",
        "status": "completed",
        "ShotPlan": [{
            "shot_id": "S01",
            "action_path": "Presenter demonstrates the product",
            "dialogue_or_voiceover": "See the result now",
            "approval_status": "APPROVED",
            "approved_by": "human:reviewer",
        }],
    }
    panel_plan = {
        "task_id": "old-task-001",
        "panels": [{
            "panel_id": "S01-P01",
            "camera_motion": {"structured_definition": "push in"},
            "character_state": "same presenter",
            "scene_state": "same studio",
        }],
    }
    script_root = root / "storyboard" / "production_storyboard_plan"
    _write(script_root / "production_storyboard_plan.json", json.dumps(plan))
    _write(script_root / "production_storyboard_panel_plan.json", json.dumps(panel_plan))

    character = b"synthetic-character-image"
    _write(root / "image_panel" / "deliverables" / "character-anchor-A.png", character)
    _write(root / "image_panel" / "workspace" / "refs" / "character-anchor-A.png", character)
    _write(root / "image_panel" / "deliverables" / "scene-anchor-A.png", b"synthetic-scene-image")
    _write(root / "image_panel" / "deliverables" / "S01-P01.png", b"synthetic-panel-image")
    _write(root / "image_panel" / "workspace" / "refs" / "product-front.jpg", b"synthetic-product-image")
    _write(root / "creative" / "lighting-reference.webp", b"synthetic-other-image")

    _write(root / "video_planning" / "storyboard_master_sheet_001.png", b"sheet")
    _write(root / "image_panel" / "workspace" / "output" / "provider.png", b"provider-output")
    _write(root / "video_generation" / "seedance_nz_video_receipt.json", "{}")
    _write(root / "video_generation" / "seedance_nz_video.mp4", b"video")


class ProjectCopyTests(unittest.TestCase):
    def test_inspect_groups_deduplicates_and_excludes_execution_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            _project_fixture(source)
            before = _tree_snapshot(source)

            inventory = inspect_project(source)

            after = _tree_snapshot(source)

        self.assertEqual(
            [item["relative_path"] for item in inventory["scripts"]],
            [
                "storyboard/production_storyboard_plan/production_storyboard_panel_plan.json",
                "storyboard/production_storyboard_plan/production_storyboard_plan.json",
            ],
        )
        self.assertEqual(len(inventory["assets"]["character"]), 1)
        self.assertEqual(len(inventory["assets"]["scene"]), 1)
        self.assertEqual(len(inventory["assets"]["product"]), 1)
        self.assertEqual(len(inventory["assets"]["storyboard_panel"]), 1)
        self.assertEqual(len(inventory["assets"]["other_reference"]), 1)
        self.assertIn("/deliverables/", "/" + inventory["assets"]["character"][0]["relative_path"])
        self.assertRegex(inventory["inventory_digest"], r"^sha256:[0-9a-f]{64}$")
        for group in inventory["assets"].values():
            for item in group:
                self.assertRegex(item["sha256"], r"^sha256:[0-9a-f]{64}$")
        all_paths = json.dumps(inventory, ensure_ascii=False)
        self.assertNotIn("storyboard_master_sheet_001.png", all_paths)
        self.assertNotIn("provider.png", all_paths)
        self.assertNotIn("seedance_nz_video", all_paths)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
