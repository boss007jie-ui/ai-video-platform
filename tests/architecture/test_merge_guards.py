from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_video_platform.maintenance.codex.merge_guard import (
    check_changed_paths,
    scan_runtime_boundaries,
)


class MergeGuardTests(unittest.TestCase):
    def test_changed_path_guard_enforces_exclusive_owners(self) -> None:
        self.assertEqual(
            check_changed_paths(
                "codex-03",
                (
                    "src/ai_video_platform/skills/storyboard/domain/story.py",
                    "docs/contracts/change-requests/codex-03/storyboard.md",
                ),
            ),
            (),
        )
        violation = check_changed_paths(
            "codex-03",
            ("src/ai_video_platform/contracts/registry.py",),
        )
        self.assertEqual(violation[0].rule_id, "OWNERSHIP_PATH_FORBIDDEN")
        self.assertEqual(violation[0].path, "src/ai_video_platform/contracts/registry.py")
        self.assertEqual(
            check_changed_paths(
                "codex-00",
                ("src/ai_video_platform/skills/storyboard/application/service.py",),
            )[0].rule_id,
            "OWNERSHIP_PATH_FORBIDDEN",
        )

    def test_runtime_scan_blocks_cross_skill_private_import_and_library_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storyboard = root / "src" / "ai_video_platform" / "skills" / "storyboard"
            storyboard.mkdir(parents=True)
            (storyboard / "bad.py").write_text(
                "from ai_video_platform.skills.video_generation.domain import job\n",
                encoding="utf-8",
            )
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writer.py").write_text(
                "from pathlib import Path\n"
                "Path('AI Video Product Library/item.json').write_text('x')\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            {violation.rule_id for violation in violations},
            {"CROSS_SKILL_PRIVATE_IMPORT", "PRODUCT_LIBRARY_WRITER_FORBIDDEN"},
        )


if __name__ == "__main__":
    unittest.main()
