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

    def test_runtime_scan_blocks_chained_lambda_and_os_library_writers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writers.py").write_text(
                "import os\n"
                "from pathlib import Path\n"
                "joinpath_writer = lambda: Path('AI Video Product Library').joinpath('item.json').write_text('x')\n"
                "def replace_writer():\n"
                "    os.replace('temporary.json', 'AI Video Research Library/item.json')\n"
                "def mkdir_writer():\n"
                "    os.mkdir('AI Video Product Library/new-folder')\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            {violation.rule_id for violation in violations},
            {
                "PRODUCT_LIBRARY_WRITER_FORBIDDEN",
                "RESEARCH_LIBRARY_WRITER_FORBIDDEN",
            },
        )

    def test_runtime_scan_blocks_instance_attribute_library_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writer.py").write_text(
                "from pathlib import Path\n"
                "class ReviewWriter:\n"
                "    def __init__(self):\n"
                "        self.root = Path('AI Video Research Library')\n"
                "    def write(self):\n"
                "        (self.root / 'item.json').write_text('x')\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            [violation.rule_id for violation in violations],
            ["RESEARCH_LIBRARY_WRITER_FORBIDDEN"],
        )

    def test_runtime_scan_respects_function_local_shadowing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "local_writer.py").write_text(
                "from pathlib import Path\n"
                "LIBRARY_ROOT = 'AI Video Product Library'\n"
                "def write_local():\n"
                "    LIBRARY_ROOT = 'local-review-output'\n"
                "    Path(LIBRARY_ROOT).write_text('ok')\n",
                encoding="utf-8",
            )

            self.assertEqual(scan_runtime_boundaries(root), ())

    def test_runtime_scan_allows_only_canonical_cross_skill_public_seams(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skills = root / "src" / "ai_video_platform" / "skills"
            storyboard = skills / "storyboard"
            storyboard.mkdir(parents=True)
            (storyboard / "__init__.py").write_text(
                "from .interface import StoryboardService\n"
                "__all__ = ['StoryboardService']\n",
                encoding="utf-8",
            )
            qa = skills / "qa_review"
            qa.mkdir(parents=True)
            (qa / "public_imports.py").write_text(
                "from ai_video_platform.skills.storyboard import StoryboardService\n"
                "from ai_video_platform.skills.storyboard.cli import main\n"
                "from ai_video_platform.skills.storyboard.interface import StoryboardRequest\n",
                encoding="utf-8",
            )

            self.assertEqual(scan_runtime_boundaries(root), ())

            (qa / "private_import.py").write_text(
                "from ai_video_platform.skills.storyboard.domain import StoryboardPlan\n",
                encoding="utf-8",
            )
            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            [violation.rule_id for violation in violations],
            ["CROSS_SKILL_PRIVATE_IMPORT"],
        )

    def test_runtime_scan_blocks_private_module_imported_through_skill_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skills = root / "src" / "ai_video_platform" / "skills"
            storyboard = skills / "storyboard"
            storyboard.mkdir(parents=True)
            (storyboard / "__init__.py").write_text(
                "from .interface import StoryboardService\n"
                "__all__ = ['StoryboardService']\n",
                encoding="utf-8",
            )
            (storyboard / "domain.py").write_text("class StoryboardPlan: pass\n", encoding="utf-8")
            qa = skills / "qa_review"
            qa.mkdir()
            (qa / "imports.py").write_text(
                "from ai_video_platform.skills.storyboard import StoryboardService\n"
                "from ai_video_platform.skills.storyboard import domain\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            [violation.rule_id for violation in violations],
            ["CROSS_SKILL_PRIVATE_IMPORT"],
        )

    def test_runtime_scan_models_callable_defaults_and_parameter_shadowing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writers.py").write_text(
                "from pathlib import Path\n"
                "PRODUCT_ROOT = Path('AI Video Product Library')\n"
                "lambda_writer = lambda root=PRODUCT_ROOT: root.write_text('x')\n"
                "def research_writer(root=Path('AI Video Research Library')):\n"
                "    root.write_text('x')\n"
                "def local_writer(PRODUCT_ROOT):\n"
                "    PRODUCT_ROOT.write_text('ok')\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            {violation.rule_id for violation in violations},
            {
                "PRODUCT_LIBRARY_WRITER_FORBIDDEN",
                "RESEARCH_LIBRARY_WRITER_FORBIDDEN",
            },
        )

    def test_runtime_scan_blocks_aliased_os_library_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writer.py").write_text(
                "import os as filesystem\n"
                "filesystem.replace('temporary.json', 'AI Video Research Library/item.json')\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            [violation.rule_id for violation in violations],
            ["RESEARCH_LIBRARY_WRITER_FORBIDDEN"],
        )

    def test_runtime_scan_blocks_library_path_passed_to_local_writer_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writer.py").write_text(
                "from pathlib import Path\n"
                "PRODUCT_ROOT = Path('AI Video Product Library')\n"
                "def write_report(root):\n"
                "    root.write_text('x')\n"
                "write_report(PRODUCT_ROOT)\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            [violation.rule_id for violation in violations],
            ["PRODUCT_LIBRARY_WRITER_FORBIDDEN"],
        )

    def test_runtime_scan_blocks_private_import_through_relative_skills_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storyboard = root / "src" / "ai_video_platform" / "skills" / "storyboard"
            storyboard.mkdir(parents=True)
            (storyboard / "domain.py").write_text("class StoryboardPlan: pass\n", encoding="utf-8")
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir()
            (qa / "imports.py").write_text(
                "from ...skills.storyboard.domain import StoryboardPlan\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            [violation.rule_id for violation in violations],
            ["CROSS_SKILL_PRIVATE_IMPORT"],
        )

    def test_runtime_scan_blocks_from_import_aliased_library_writers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writers.py").write_text(
                "from os import replace as relocate\n"
                "from shutil import copy2 as duplicate\n"
                "relocate('temporary.json', 'AI Video Research Library/item.json')\n"
                "duplicate('temporary.json', 'AI Video Product Library/item.json')\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            {violation.rule_id for violation in violations},
            {
                "PRODUCT_LIBRARY_WRITER_FORBIDDEN",
                "RESEARCH_LIBRARY_WRITER_FORBIDDEN",
            },
        )

    def test_runtime_scan_blocks_two_hop_local_writer_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writer.py").write_text(
                "from pathlib import Path\n"
                "PRODUCT_ROOT = Path('AI Video Product Library')\n"
                "def sink(root):\n"
                "    root.write_text('x')\n"
                "def wrapper(root):\n"
                "    sink(root)\n"
                "wrapper(PRODUCT_ROOT)\n",
                encoding="utf-8",
            )

            violations = scan_runtime_boundaries(root)

        self.assertEqual(
            [violation.rule_id for violation in violations],
            ["PRODUCT_LIBRARY_WRITER_FORBIDDEN"],
        )

    def test_runtime_scan_blocks_invoked_writer_lambda(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qa = root / "src" / "ai_video_platform" / "skills" / "qa_review"
            qa.mkdir(parents=True)
            (qa / "writer.py").write_text(
                "from pathlib import Path\n"
                "RESEARCH_ROOT = Path('AI Video Research Library')\n"
                "writer = lambda root: root.write_text('x')\n"
                "writer(RESEARCH_ROOT)\n",
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
