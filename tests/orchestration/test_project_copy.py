from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.orchestration.project_copy import ProjectCopyError, copy_project, inspect_project, main


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
        "contract_id": "old-contract-001",
        "producer": {"agent": "skill"},
        "source_provenance": [{"contract_id": "source-contract-001"}],
        "status": "completed",
        "product_id": "product-laser-pointer",
        "cta": "Buy the laser pointer today",
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
    _write(root / "CTA_OPTIONS.md", "CTA A: Buy now\nCTA B: Learn more\n")

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
                "CTA_OPTIONS.md",
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

    def test_copy_preserves_full_creative_script_and_only_selected_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "copied-project"
            source.mkdir()
            _project_fixture(source)
            before = _tree_snapshot(source)
            source_cta = (source / "CTA_OPTIONS.md").read_bytes()
            inventory = inspect_project(source)
            character = inventory["assets"]["character"][0]
            scene = inventory["assets"]["scene"][0]
            request = {
                "source_project": str(source),
                "destination_project": str(destination),
                "project_id": "copied-project-001",
                "inventory_digest": inventory["inventory_digest"],
                "selected_candidate_ids": [character["candidate_id"], scene["candidate_id"]],
            }

            result = copy_project(
                request,
                now=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
            )

            copied_plan_record = next(
                item for item in result["scripts"]
                if item["source_relative_path"].endswith("production_storyboard_plan.json")
            )
            copied_plan = json.loads(
                (destination / copied_plan_record["copied_relative_path"]).read_text(encoding="utf-8")
            )
            copied_cta_record = next(
                item for item in result["scripts"]
                if item["source_relative_path"] == "CTA_OPTIONS.md"
            )
            copied_cta = (destination / copied_cta_record["copied_relative_path"]).read_bytes()
            copied_asset_bytes = {
                item["role"]: (destination / item["copied_relative_path"]).read_bytes()
                for item in result["assets"]
            }
            persisted = json.loads((destination / "PROJECT_COPY.json").read_text(encoding="utf-8"))
            destination_paths = set(_tree_snapshot(destination))
            copied_json_text = "".join(
                path.read_text(encoding="utf-8")
                for path in destination.rglob("*.json")
            )
            after = _tree_snapshot(source)

        self.assertEqual(result, persisted)
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["created_at"], "2026-07-28T08:00:00Z")
        self.assertEqual({item["role"] for item in result["assets"]}, {"character", "scene"})
        self.assertEqual(copied_asset_bytes["character"], b"synthetic-character-image")
        self.assertEqual(copied_asset_bytes["scene"], b"synthetic-scene-image")
        self.assertEqual(copied_cta, source_cta)
        self.assertEqual(copied_plan["document_type"], "project-copy-draft-script-v1")
        content = copied_plan["content"]
        self.assertEqual(content["product_id"], "product-laser-pointer")
        self.assertEqual(content["cta"], "Buy the laser pointer today")
        self.assertEqual(content["ShotPlan"][0]["action_path"], "Presenter demonstrates the product")
        self.assertEqual(content["ShotPlan"][0]["dialogue_or_voiceover"], "See the result now")
        serialized_content = json.dumps(content, ensure_ascii=False)
        for excluded in (
            "task_id", "artifact_id", "contract_id", "producer", "source_provenance",
            "approval_status", "approved_by",
        ):
            self.assertNotIn(f'"{excluded}"', serialized_content)
        self.assertNotIn('"status"', serialized_content)
        self.assertEqual(
            len([path for path in destination_paths if path.startswith("reuse_source/assets/")]),
            2,
        )
        self.assertNotIn("old-task-001", copied_json_text)
        self.assertFalse(any(path.endswith((".mp4", "receipt.json")) for path in destination_paths))
        self.assertEqual(after, before)

    def test_inspect_rejects_missing_script_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty"
            empty.mkdir()
            with self.assertRaisesRegex(ProjectCopyError, "no reusable script"):
                inspect_project(empty)

            source = root / "source"
            source.mkdir()
            _project_fixture(source)
            try:
                (source / "linked-image.png").symlink_to(
                    source / "image_panel" / "deliverables" / "scene-anchor-A.png"
                )
            except OSError:
                return
            with self.assertRaisesRegex(ProjectCopyError, "symlink"):
                inspect_project(source)

    def test_copy_rejects_unknown_stale_existing_and_nested_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            _project_fixture(source)
            inventory = inspect_project(source)

            def request_for(destination: Path) -> dict[str, object]:
                return {
                    "source_project": str(source),
                    "destination_project": str(destination),
                    "project_id": "copied-project-001",
                    "inventory_digest": inventory["inventory_digest"],
                    "selected_candidate_ids": [],
                }

            unknown = request_for(root / "unknown")
            unknown["selected_candidate_ids"] = ["asset:scene:" + "0" * 64]
            with self.assertRaisesRegex(ProjectCopyError, "not in the inspected project"):
                copy_project(unknown)

            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(ProjectCopyError, "already exists"):
                copy_project(request_for(existing))

            with self.assertRaisesRegex(ProjectCopyError, "outside the source"):
                copy_project(request_for(source / "nested-copy"))

            scene = source / "image_panel" / "deliverables" / "scene-anchor-A.png"
            scene.write_bytes(b"changed-scene")
            stale = request_for(root / "stale")
            with self.assertRaisesRegex(ProjectCopyError, "changed after inspection"):
                copy_project(stale)
            self.assertFalse((root / "stale").exists())

    def test_invalid_script_copy_removes_incomplete_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            _project_fixture(source)
            script = source / "storyboard" / "production_storyboard_plan" / "production_storyboard_plan.json"
            script.write_text("{broken", encoding="utf-8")
            inventory = inspect_project(source)
            destination = root / "invalid-script-copy"
            request = {
                "source_project": str(source),
                "destination_project": str(destination),
                "project_id": "copied-project-001",
                "inventory_digest": inventory["inventory_digest"],
                "selected_candidate_ids": [],
            }

            with self.assertRaisesRegex(ProjectCopyError, "script JSON is invalid"):
                copy_project(request)

            self.assertFalse(destination.exists())

    def test_cli_inspects_and_copies_with_machine_readable_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            _project_fixture(source)

            output = io.StringIO()
            with redirect_stdout(output):
                inspect_code = main(["inspect", "--source", str(source)])
            inspected = json.loads(output.getvalue())
            character_id = inspected["result"]["assets"]["character"][0]["candidate_id"]

            request_path = root / "copy-request.json"
            request_path.write_text(json.dumps({
                "source_project": str(source),
                "destination_project": str(root / "copied"),
                "project_id": "copied-project-001",
                "inventory_digest": inspected["result"]["inventory_digest"],
                "selected_candidate_ids": [character_id],
            }), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                copy_code = main(["copy", "--request", str(request_path)])
            copied = json.loads(output.getvalue())

        self.assertEqual((inspect_code, copy_code), (0, 0))
        self.assertTrue(inspected["ok"])
        self.assertTrue(copied["ok"])
        self.assertEqual(copied["result"]["project_id"], "copied-project-001")
        self.assertEqual([item["role"] for item in copied["result"]["assets"]], ["character"])

    def test_cli_rejects_invalid_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "invalid.json"
            request_path.write_text("{broken", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["copy", "--request", str(request_path)])
            response = json.loads(output.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertFalse(response["ok"])
        self.assertIsInstance(response["error"], str)


if __name__ == "__main__":
    unittest.main()
