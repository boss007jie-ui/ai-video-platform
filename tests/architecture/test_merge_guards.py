from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_video_platform.maintenance.codex.merge_guard import (
    check_changed_paths,
    scan_runtime_boundaries,
)


class MergeGuardTests(unittest.TestCase):
    def test_runtime_scan_allows_library_rejection_guard_with_unrelated_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "guard.py").write_text(
                "from pathlib import Path\n"
                "PRODUCT_LIBRARY = 'AI Video Product Library'\n"
                "def reject_product_library(path):\n"
                "    if PRODUCT_LIBRARY in str(path):\n"
                "        raise PermissionError('library writes are forbidden')\n"
                "def write_local_report():\n"
                "    Path('local-review-report.json').write_text('ok')\n",
                encoding="utf-8",
            )

            self.assertEqual(scan_runtime_boundaries(root), ())

    def test_runtime_scan_blocks_function_literal_library_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writer.py").write_text(
                "from pathlib import Path\n"
                "def write_review():\n"
                "    Path('AI Video Product Library/item.json').write_text('x')\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            [violation.rule_id for violation in violations],
            ["PRODUCT_LIBRARY_WRITER_FORBIDDEN"],
        )

    def test_runtime_scan_blocks_module_constant_library_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writer.py").write_text(
                "from pathlib import Path\n"
                "RESEARCH_LIBRARY = 'AI Video Research Library'\n"
                "def write_review():\n"
                "    target = Path(RESEARCH_LIBRARY) / 'item.json'\n"
                "    target.write_text('x')\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            [violation.rule_id for violation in violations],
            ["RESEARCH_LIBRARY_WRITER_FORBIDDEN"],
        )

    def test_runtime_scan_allows_ft1_skill_implementation_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "src" / "ai_video_platform" / "skills" / "storyboard"
            (skill / "public_api").mkdir(parents=True)
            (skill / "adapters").mkdir()
            (skill / "__init__.py").write_text("from .public_api.interface import run\n", encoding="utf-8")
            (skill / "SKILL.md").write_text("# Storyboard\n", encoding="utf-8")
            (skill / "public_api" / "interface.py").write_text(
                "def run(payload):\n    return payload\n",
                encoding="utf-8",
            )
            (skill / "adapters" / "fake.py").write_text(
                "class FakeAdapter:\n    pass\n",
                encoding="utf-8",
            )

            self.assertEqual(scan_runtime_boundaries(root), ())

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
                "from ..video_generation.domain import job\n",
                encoding="utf-8",
            )
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writer.py").write_text(
                "from pathlib import Path\n"
                "target = Path('AI Video Product Library/item.json')\n"
                "target.open('w').write('x')\n"
                "research = Path('AI Video Research Library/item.json')\n"
                "research.write_text('x')\n",
                encoding="utf-8",
            )
            (qa / "network.py").write_text("import requests\n", encoding="utf-8")
            (qa / "legacy.py").write_text("SOURCE = 'veo3.1-production'\n", encoding="utf-8")

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            {violation.rule_id for violation in violations},
            {
                "CROSS_SKILL_PRIVATE_IMPORT",
                "PRODUCT_LIBRARY_WRITER_FORBIDDEN",
                "RESEARCH_LIBRARY_WRITER_FORBIDDEN",
                "NETWORK_CLIENT_IMPORT_FORBIDDEN",
                "LEGACY_RUNTIME_PATH_FORBIDDEN",
            },
        )


if __name__ == "__main__":
    unittest.main()
