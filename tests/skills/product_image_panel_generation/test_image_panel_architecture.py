from __future__ import annotations

import ast
from pathlib import Path
from typing import Mapping
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = REPOSITORY_ROOT / "src" / "ai_video_platform"
ALLOWED_INTERNAL_GENERATE_CALLERS = frozenset(
    {
        "ai_video_platform/skills/product_image_panel_generation/adapters.py",
        "ai_video_platform/skills/product_image_panel_generation/service.py",
    }
)


def _find_forbidden_generate_calls(sources: Mapping[str, str]) -> tuple[str, ...]:
    violations: list[str] = []
    for relative_path, source in sorted(sources.items()):
        tree = ast.parse(source, filename=relative_path)
        if relative_path in ALLOWED_INTERNAL_GENERATE_CALLERS:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_generate":
                violations.append(f"{relative_path}:{node.lineno}")
    return tuple(sorted(violations))


class ImagePanelArchitectureTests(unittest.TestCase):
    def test_synthetic_non_allowed_module_direct_call_is_detected(self) -> None:
        violations = _find_forbidden_generate_calls(
            {"ai_video_platform/skills/product_image_panel_generation/rogue.py": "adapter._generate(invocation)\n"}
        )

        self.assertEqual(
            violations,
            ("ai_video_platform/skills/product_image_panel_generation/rogue.py:1",),
        )

    def test_production_source_has_no_non_allowed_internal_generate_calls(self) -> None:
        sources = {
            path.relative_to(REPOSITORY_ROOT / "src").as_posix(): path.read_text(encoding="utf-8")
            for path in SOURCE_ROOT.rglob("*.py")
        }

        self.assertEqual(_find_forbidden_generate_calls(sources), ())


if __name__ == "__main__":
    unittest.main()
