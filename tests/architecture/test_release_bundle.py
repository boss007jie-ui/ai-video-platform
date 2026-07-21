from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_video_platform.maintenance.codex.release import (
    RepositoryState,
    build_release_bundle,
    read_repository_head,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _CleanRepository:
    def inspect(self, project_root: Path) -> RepositoryState:
        return RepositoryState(read_repository_head(project_root), True)


class ReleaseBundleTests(unittest.TestCase):
    def test_release_bundle_is_deterministic_and_contains_rollback_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            digest = "sha256:" + "b" * 64
            arguments = {
                "project_root": PROJECT_ROOT,
                "source_commit": read_repository_head(PROJECT_ROOT),
                "version": "0.1.0",
                "authorization_id": "FTG-0-20260720-001",
                "test_evidence": {
                    "offline-tests": {"status": "PASS", "digest": digest},
                    "reproducible-build": {"status": "PASS", "digest": digest},
                    "ownership-scan": {"status": "PASS", "digest": digest},
                    "secret-scan": {"status": "PASS", "digest": digest},
                    "license-scan": {"status": "PASS", "digest": digest},
                    "rollback-exercise": {"status": "PASS", "digest": digest},
                },
                "repository_inspector": _CleanRepository(),
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
            self.assertEqual(manifest["source_commit"], arguments["source_commit"])
            self.assertEqual(manifest["foundation_contract_count"], 11)
            self.assertEqual(manifest["provider_smoke"], "NOT_AUTHORIZED")
            self.assertRegex(manifest["wheel_sha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(rollback["strategy"], "revert-release-commit")

    def test_release_bundle_rejects_unbound_or_failed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaisesRegex(ValueError, "required release checks"):
                build_release_bundle(
                    project_root=PROJECT_ROOT,
                    output_dir=Path(output),
                    source_commit=read_repository_head(PROJECT_ROOT),
                    version="0.1.0",
                    authorization_id="FTG-0-20260720-001",
                    test_evidence={"offline-tests": {"status": "FAIL", "digest": "sha256:" + "c" * 64}},
                    repository_inspector=_CleanRepository(),
                )

    def test_dependency_lock_matches_dependency_free_project(self) -> None:
        lock = (PROJECT_ROOT / "requirements.lock").read_text(encoding="utf-8")
        self.assertIn("runtime_dependencies = []", lock)


if __name__ == "__main__":
    unittest.main()
