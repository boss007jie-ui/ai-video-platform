"""Mechanical ownership and runtime-boundary checks for merge candidates."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


@dataclass(frozen=True, slots=True)
class MergeViolation:
    rule_id: str
    path: str
    detail: str


_WORKLINE_PREFIXES = {
    "codex-01": ("src/ai_video_platform/skills/product_knowledge/", "tests/skills/product_knowledge/"),
    "codex-02": (
        "src/ai_video_platform/skills/viral_research_asset_collection/",
        "src/ai_video_platform/skills/reference_analysis/",
        "tests/skills/viral_research_asset_collection/",
        "tests/skills/reference_analysis/",
    ),
    "codex-03": ("src/ai_video_platform/skills/storyboard/", "tests/skills/storyboard/"),
    "codex-04": (
        "src/ai_video_platform/skills/product_image_panel_generation/",
        "tests/skills/product_image_panel_generation/",
    ),
    "codex-05": (
        "src/ai_video_platform/skills/storyboard_master_video_planning/",
        "src/ai_video_platform/skills/video_generation/",
        "tests/skills/storyboard_master_video_planning/",
        "tests/skills/video_generation/",
    ),
    "codex-06": (
        "src/ai_video_platform/skills/qa_review/",
        "tests/skills/qa_review/",
        "tests/integration/",
        "tests/golden/",
        "fixtures/integration/",
        "fixtures/golden/",
    ),
}
_CODEX_00_PREFIXES = (
    ".github/",
    "contracts/",
    "core/",
    "release/",
    "src/ai_video_platform/contracts/",
    "src/ai_video_platform/core/",
    "src/ai_video_platform/cli/root/",
    "src/ai_video_platform/orchestration/hermes/",
    "src/ai_video_platform/maintenance/codex/",
    "schemas/",
    "fixtures/contracts/",
    "tests/contracts/",
    "tests/architecture/",
    "tests/security/",
    "tests/orchestration/",
    "tools/release/",
    "tools/migration/",
    "tools/verification/",
    "docs/architecture/",
    "docs/contracts/",
    "docs/operations/",
    "docs/maintenance/",
)
_CODEX_00_EXACT = {
    ".gitignore",
    "README.md",
    "pyproject.toml",
    "requirements.lock",
    "src/ai_video_platform/__init__.py",
    "src/ai_video_platform/build_backend.py",
    "src/ai_video_platform/skills/__init__.py",
    "tools/run_offline_tests.py",
}
_LEGACY_MARKERS = {
    "04-视频",
    "veo3.1-production",
    "veo3.1-catpaw-dev",
    "veo3.1-seedance-skill-sandbox",
    "ai-video-reference-gap-analyzer",
    "veo3.1-seedance-skill-runtime",
}


def _normalize(relative_path: str) -> str:
    path = PurePosixPath(relative_path.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return ""
    return path.as_posix()


def _is_allowed(workline_id: str, path: str) -> bool:
    if workline_id == "codex-00":
        request_prefix = "docs/contracts/change-requests/"
        dependency_prefix = "docs/dependencies/change-requests/"
        if path.startswith(request_prefix) or path.startswith(dependency_prefix):
            return path.startswith(f"{request_prefix}codex-00/") or path.startswith(
                f"{dependency_prefix}codex-00/"
            )
        return path in _CODEX_00_EXACT or any(path.startswith(prefix) for prefix in _CODEX_00_PREFIXES)
    prefixes = _WORKLINE_PREFIXES.get(workline_id)
    if prefixes is None:
        return False
    request_prefixes = (
        f"docs/contracts/change-requests/{workline_id}/",
        f"docs/dependencies/change-requests/{workline_id}/",
    )
    return any(path.startswith(prefix) for prefix in (*prefixes, *request_prefixes))


def check_changed_paths(workline_id: str, changed_paths: Iterable[str]) -> tuple[MergeViolation, ...]:
    violations: list[MergeViolation] = []
    for supplied_path in changed_paths:
        path = _normalize(supplied_path)
        if not path or not _is_allowed(workline_id, path):
            violations.append(
                MergeViolation(
                    "OWNERSHIP_PATH_FORBIDDEN",
                    supplied_path.replace("\\", "/"),
                    f"Path is not owned by {workline_id}",
                )
            )
    return tuple(violations)


def _skill_for_path(path: Path) -> str | None:
    parts = path.as_posix().split("/")
    try:
        index = parts.index("skills")
    except ValueError:
        return None
    return parts[index + 1] if len(parts) > index + 1 else None


def _cross_skill_imports(tree: ast.AST, owner_skill: str | None) -> bool:
    if owner_skill is None:
        return False
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        for module in modules:
            parts = module.split(".")
            if len(parts) < 3 or parts[:2] != ["ai_video_platform", "skills"]:
                continue
            target_skill = parts[2]
            exposed_area = parts[3] if len(parts) > 3 else ""
            if target_skill != owner_skill and exposed_area not in {"public_api", "cli"}:
                return True
    return False


def _write_call_text(tree: ast.AST) -> tuple[str, ...]:
    calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        is_write = isinstance(function, ast.Attribute) and function.attr in {
            "write_text", "write_bytes", "mkdir", "touch", "unlink", "rename", "replace"
        }
        if isinstance(function, ast.Name) and function.id == "open":
            mode_nodes = [*node.args[1:2], *[item.value for item in node.keywords if item.arg == "mode"]]
            is_write = any(isinstance(item, ast.Constant) and any(flag in str(item.value) for flag in "wax+") for item in mode_nodes)
        if is_write:
            calls.append(ast.unparse(node))
    return tuple(calls)


def scan_runtime_boundaries(project_root: Path) -> tuple[MergeViolation, ...]:
    violations: list[MergeViolation] = []
    source_root = project_root / "src"
    for path in sorted(source_root.rglob("*.py")) if source_root.exists() else ():
        relative = path.relative_to(project_root)
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=relative.as_posix())
        owner_skill = _skill_for_path(relative)
        if _cross_skill_imports(tree, owner_skill):
            violations.append(MergeViolation("CROSS_SKILL_PRIVATE_IMPORT", relative.as_posix(), "Use public_api or cli"))
        lowered = text.lower()
        if path.name != "merge_guard.py" and any(marker.lower() in lowered for marker in _LEGACY_MARKERS):
            violations.append(MergeViolation("LEGACY_RUNTIME_PATH_FORBIDDEN", relative.as_posix(), "Legacy runtime dependency detected"))
        for call in _write_call_text(tree):
            if "AI Video Product Library" in call and owner_skill != "product_knowledge":
                violations.append(MergeViolation("PRODUCT_LIBRARY_WRITER_FORBIDDEN", relative.as_posix(), "Only Product Knowledge may write Product Library"))
                break
            if "AI Video Research Library" in call and owner_skill != "viral_research_asset_collection":
                violations.append(MergeViolation("RESEARCH_LIBRARY_WRITER_FORBIDDEN", relative.as_posix(), "Only Viral Research may write Research Library"))
                break
    return tuple(violations)
