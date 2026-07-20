from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_video_platform.maintenance.codex.release import build_release_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReleaseBundleTests(unittest.TestCase):
    def test_release_bundle_is_deterministic_and_contains_rollback_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            arguments = {
                "project_root": PROJECT_ROOT,
                "source_commit": "a" * 40,
                "version": "0.2.0-rc.1",
                "authorization_id": "FTG-0-20260720-001",
                "test_evidence": {"offline": "68 tests, OK"},
            }
            first = build_release_bundle(output_dir=Path(first_dir), **arguments)
            second = build_release_bundle(output_dir=Path(second_dir), **arguments)

            self.assertEqual(first, second)
            self.assertEqual(
                set(first),
                {"release-manifest.json", "sbom.spdx.json", "license-inventory.json", "rollback.json"},
            )
            manifest = json.loads((Path(first_dir) / "release-manifest.json").read_text(encoding="utf-8"))
            rollback = json.loads((Path(first_dir) / "rollback.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_commit"], "a" * 40)
            self.assertEqual(manifest["foundation_contract_count"], 11)
            self.assertEqual(manifest["provider_smoke"], "NOT_AUTHORIZED")
            self.assertEqual(rollback["strategy"], "revert-release-commit")

    def test_dependency_lock_matches_dependency_free_project(self) -> None:
        lock = (PROJECT_ROOT / "requirements.lock").read_text(encoding="utf-8")
        self.assertIn("runtime_dependencies = []", lock)


if __name__ == "__main__":
    unittest.main()
