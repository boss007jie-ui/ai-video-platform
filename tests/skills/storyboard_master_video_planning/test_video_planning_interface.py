from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.storyboard_master_video_planning import VideoPlanningInterface
from ai_video_platform.skills.storyboard_master_video_planning.cli import run_cli


def planning_request() -> dict[str, object]:
    return {
        "task_id": "task-planning-001",
        "expected_storyboard_revision": 3,
        "expected_asset_manifest_revision": 7,
        "storyboard": {
            "storyboard_id": "storyboard-001",
            "revision": 3,
            "shots": [
                {
                    "shot_id": "shot-002",
                    "sequence": 2,
                    "required_asset_roles": ["hero"],
                    "continuity_group": "product-lock",
                    "visual_anchor": {"product_angle": "front-three-quarter"},
                    "motion": {"kind": "push-in", "duration_ms": 1200},
                },
                {
                    "shot_id": "shot-001",
                    "sequence": 1,
                    "required_asset_roles": ["hero"],
                    "continuity_group": "product-lock",
                    "visual_anchor": {"product_angle": "front-three-quarter"},
                    "motion": {"kind": "hold", "duration_ms": 800},
                },
            ],
        },
        "asset_manifest": {
            "manifest_id": "manifest-001",
            "manifest_revision": 7,
            "storyboard_id": "storyboard-001",
            "storyboard_revision": 3,
            "assets": [
                {
                    "asset_id": "asset-hero",
                    "role": "hero",
                    "shot_ids": ["shot-001", "shot-002"],
                    "approval_state": "approved",
                    "uri": "memory://asset-hero.png",
                    "sha256": "sha256:" + "a" * 64,
                }
            ],
        },
    }


class VideoPlanningInterfaceTests(unittest.TestCase):
    def test_build_video_plan_is_deterministic_versioned_and_provider_free(self) -> None:
        interface = VideoPlanningInterface()
        request = planning_request()

        first = interface.build_video_plan(request)
        reordered = json.loads(json.dumps(request, sort_keys=True))
        second = interface.build_video_plan(reordered)

        self.assertEqual(first, second)
        self.assertEqual(first["artifact_name"], "VideoExecutionPackage")
        self.assertEqual(first["schema_version"], "0.1.0")
        self.assertEqual(first["contract_status"], "DRAFT_UNREGISTERED")
        self.assertFalse(first["planning_provider_submission_performed"])
        self.assertEqual([item["shot_id"] for item in first["storyboard_master"]["shots"]], ["shot-001", "shot-002"])
        self.assertEqual(len(first["asset_mapping"]), 2)
        self.assertEqual(len(first["motion_plan"]), 2)
        self.assertTrue(first["package_digest"].startswith("sha256:"))

    def test_compose_master_snapshots_input_and_freezes_continuity_anchor(self) -> None:
        interface = VideoPlanningInterface()
        request = planning_request()

        master = interface.compose_storyboard_master(request)
        request["storyboard"]["shots"][0]["visual_anchor"]["product_angle"] = "changed"

        self.assertEqual(master["visual_anchors"][0]["anchor"], {"product_angle": "front-three-quarter"})
        self.assertEqual(master["contract_status"], "DRAFT_UNREGISTERED")

    def test_validate_video_plan_accepts_untampered_package(self) -> None:
        interface = VideoPlanningInterface()
        package = interface.build_video_plan(planning_request())

        result = interface.validate_video_plan(package)

        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["package_digest"], package["package_digest"])
        self.assertEqual(result["schema_version"], "0.1.0")
        self.assertEqual(result["contract_status"], "DRAFT_UNREGISTERED")

    def test_cli_returns_machine_readable_success(self) -> None:
        result = run_cli("build-video-plan", planning_request())

        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["artifact_name"], "VideoExecutionPackage")


if __name__ == "__main__":
    unittest.main()
