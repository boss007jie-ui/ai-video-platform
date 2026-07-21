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
_SKILL_NAMES = {
    "product_knowledge",
    "viral_research_asset_collection",
    "reference_analysis",
    "storyboard",
    "product_image_panel_generation",
    "storyboard_master_video_planning",
    "video_generation",
    "qa_review",
}
_NETWORK_IMPORTS = {"requests", "httpx", "urllib.request", "aiohttp"}
_PROVIDER_IMPORTS = {"openai", "google.generativeai", "replicate", "fal_client", "apify_client"}


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
            first = node.module.split(".")[0]
            if node.level >= 2 and first in _SKILL_NAMES and first != owner_skill:
                return True
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


_LIBRARY_MARKERS = {
    "product": "ai video product library",
    "research": "ai video research library",
}
_PATH_WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "touch", "unlink"}
_PATH_RELOCATION_METHODS = {"rename", "replace"}
_COPY_MOVE_FUNCTIONS = {"copy", "copy2", "copyfile", "copytree", "move"}


class _ScopeCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.assignments: list[tuple[ast.expr, ast.expr]] = []
        self.calls: list[ast.Call] = []
        self.children: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        self.assignments.extend((target, node.value) for target in node.targets)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.assignments.append((node.target, node.value))
            self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.assignments.append((node.target, node.value))
        self.visit(node.value)

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.children.append(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.children.append(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.children.append(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _assigned_names(target: ast.expr) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.Tuple, ast.List)):
        return tuple(name for item in target.elts for name in _assigned_names(item))
    return ()


def _expression_library_markers(
    expression: ast.AST | None,
    bindings: dict[str, frozenset[str]],
) -> frozenset[str]:
    if expression is None:
        return frozenset()
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        lowered = expression.value.lower()
        return frozenset(kind for kind, marker in _LIBRARY_MARKERS.items() if marker in lowered)
    if isinstance(expression, ast.Name):
        return bindings.get(expression.id, frozenset())
    if isinstance(expression, ast.BinOp):
        return _expression_library_markers(expression.left, bindings) | _expression_library_markers(
            expression.right,
            bindings,
        )
    if isinstance(expression, ast.JoinedStr):
        return frozenset().union(
            *(_expression_library_markers(value, bindings) for value in expression.values)
        )
    if isinstance(expression, ast.FormattedValue):
        return _expression_library_markers(expression.value, bindings)
    if isinstance(expression, ast.Call):
        return frozenset().union(
            *(_expression_library_markers(argument, bindings) for argument in expression.args)
        )
    return frozenset()


def _write_mode(call: ast.Call, positional_index: int) -> bool:
    mode_nodes = [
        *call.args[positional_index : positional_index + 1],
        *[item.value for item in call.keywords if item.arg == "mode"],
    ]
    return any(
        isinstance(item, ast.Constant)
        and isinstance(item.value, str)
        and any(flag in item.value for flag in "wax+")
        for item in mode_nodes
    )


def _write_target_markers(call: ast.Call, bindings: dict[str, frozenset[str]]) -> frozenset[str]:
    function = call.func
    if isinstance(function, ast.Attribute):
        if function.attr in _PATH_WRITE_METHODS:
            return _expression_library_markers(function.value, bindings)
        if function.attr in _PATH_RELOCATION_METHODS:
            targets = [function.value, *call.args[:1]]
            return frozenset().union(
                *(_expression_library_markers(target, bindings) for target in targets)
            )
        if function.attr == "open" and _write_mode(call, 0):
            return _expression_library_markers(function.value, bindings)
        if function.attr in _COPY_MOVE_FUNCTIONS:
            destinations = [
                *call.args[1:2],
                *[item.value for item in call.keywords if item.arg in {"dst", "destination"}],
            ]
            return frozenset().union(
                *(_expression_library_markers(target, bindings) for target in destinations)
            )
    if isinstance(function, ast.Name):
        if function.id == "open" and _write_mode(call, 1):
            targets = [*call.args[:1], *[item.value for item in call.keywords if item.arg == "file"]]
            return frozenset().union(
                *(_expression_library_markers(target, bindings) for target in targets)
            )
        if function.id in _COPY_MOVE_FUNCTIONS:
            destinations = [
                *call.args[1:2],
                *[item.value for item in call.keywords if item.arg in {"dst", "destination"}],
            ]
            return frozenset().union(
                *(_expression_library_markers(target, bindings) for target in destinations)
            )
    return frozenset()


def _scope_library_writes(
    scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    inherited_bindings: dict[str, frozenset[str]],
) -> frozenset[str]:
    collector = _ScopeCollector()
    for statement in scope.body:
        collector.visit(statement)
    bindings = dict(inherited_bindings)
    for _ in range(len(collector.assignments) + 1):
        changed = False
        for target, value in collector.assignments:
            markers = _expression_library_markers(value, bindings)
            for name in _assigned_names(target):
                combined = bindings.get(name, frozenset()) | markers
                if combined != bindings.get(name, frozenset()):
                    bindings[name] = combined
                    changed = True
        if not changed:
            break
    writes = frozenset().union(*(_write_target_markers(call, bindings) for call in collector.calls))
    for child in collector.children:
        writes |= _scope_library_writes(child, bindings)
    return writes


def _library_writes(tree: ast.Module) -> frozenset[str]:
    return _scope_library_writes(tree, {})


def _forbidden_runtime_import(tree: ast.AST, relative: Path) -> str | None:
    if relative.as_posix().endswith("core/guards.py"):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        else:
            continue
        for module in modules:
            if any(module == root or module.startswith(root + ".") for root in _PROVIDER_IMPORTS):
                return "PROVIDER_SDK_IMPORT_FORBIDDEN"
            if any(module == root or module.startswith(root + ".") for root in _NETWORK_IMPORTS):
                return "NETWORK_CLIENT_IMPORT_FORBIDDEN"
    return None


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
        forbidden_import = _forbidden_runtime_import(tree, relative)
        if forbidden_import:
            violations.append(MergeViolation(forbidden_import, relative.as_posix(), "Unreviewed network/provider import detected"))
        lowered = text.lower()
        if path.name != "merge_guard.py" and any(marker.lower() in lowered for marker in _LEGACY_MARKERS):
            violations.append(MergeViolation("LEGACY_RUNTIME_PATH_FORBIDDEN", relative.as_posix(), "Legacy runtime dependency detected"))
        library_writes = _library_writes(tree)
        policy_source = path.name == "merge_guard.py"
        if not policy_source and "product" in library_writes and owner_skill != "product_knowledge":
            violations.append(MergeViolation("PRODUCT_LIBRARY_WRITER_FORBIDDEN", relative.as_posix(), "Only Product Knowledge may write Product Library"))
        if not policy_source and "research" in library_writes and owner_skill != "viral_research_asset_collection":
            violations.append(MergeViolation("RESEARCH_LIBRARY_WRITER_FORBIDDEN", relative.as_posix(), "Only Viral Research may write Research Library"))
    return tuple(violations)
