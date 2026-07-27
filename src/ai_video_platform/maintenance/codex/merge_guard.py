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
        "docs/research/",
        "src/ai_video_platform/skills/viral_research_asset_collection/",
        "src/ai_video_platform/skills/reference_analysis/",
        "tests/skills/viral_research_asset_collection/",
        "tests/skills/reference_analysis/",
    ),
    "codex-03": ("src/ai_video_platform/skills/storyboard/", "tests/skills/storyboard/"),
    "codex-04": (
        "evidence/",
        "src/ai_video_platform/skills/product_image_panel_generation/",
        "tests/skills/product_image_panel_generation/",
    ),
    "codex-05": (
        "src/ai_video_platform/skills/storyboard_master_video_planning/",
        "src/ai_video_platform/skills/video_enhancement/",
        "src/ai_video_platform/skills/video_generation/",
        "tests/skills/storyboard_master_video_planning/",
        "tests/skills/video_enhancement/",
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
    "src/ai_video_platform/interfaces/",
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
    "video_enhancement",
    "video_generation",
    "qa_review",
}
_NETWORK_IMPORTS = {"requests", "httpx", "urllib.request", "aiohttp"}
_PROVIDER_IMPORTS = {"openai", "google.generativeai", "replicate", "fal_client", "apify_client"}
_AUTHORIZED_PROVIDER_NETWORK_ADAPTERS = {
    "src/ai_video_platform/skills/product_image_panel_generation/packy_image2_adapter.py",
    "src/ai_video_platform/skills/product_image_panel_generation/yunwu_adapters.py",
    "src/ai_video_platform/skills/video_generation/kie_adapter.py",
    "src/ai_video_platform/skills/video_generation/seedance_nz_adapter.py",
    "src/ai_video_platform/skills/video_enhancement/runninghub_adapter.py",
    "src/ai_video_platform/skills/viral_research_asset_collection/apify.py",
    "src/ai_video_platform/skills/viral_research_asset_collection/media.py",
}


def _normalize(relative_path: str) -> str:
    path = PurePosixPath(relative_path.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return ""
    return path.as_posix()


def _is_allowed(workline_id: str, path: str) -> bool:
    if workline_id == "integration-merge":
        return _is_allowed("codex-00", path) or any(
            _is_allowed(business_workline, path) for business_workline in _WORKLINE_PREFIXES
        )
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


def _package_public_exports(source_root: Path, skill_name: str) -> frozenset[str]:
    package_init = source_root / "ai_video_platform" / "skills" / skill_name / "__init__.py"
    if not package_init.is_file():
        return frozenset()
    package_tree = ast.parse(package_init.read_text(encoding="utf-8"), filename=package_init.as_posix())
    exports: set[str] = set()
    for node in package_tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        try:
            declared = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            continue
        if isinstance(declared, (list, tuple)):
            exports.update(item for item in declared if isinstance(item, str))
    return frozenset(exports)


def _cross_skill_imports(tree: ast.AST, owner_skill: str | None, source_root: Path) -> bool:
    if owner_skill is None:
        return False
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            relative_parts = node.module.split(".")
            if relative_parts[0] == "skills" and len(relative_parts) > 1:
                relative_parts = relative_parts[1:]
            first = relative_parts[0]
            relative_seam = relative_parts[1] if len(relative_parts) > 1 else ""
            if (
                node.level >= 2
                and first in _SKILL_NAMES
                and first != owner_skill
            ):
                if relative_seam not in _PUBLIC_SKILL_SEAMS:
                    return True
                if relative_seam == "":
                    public_exports = _package_public_exports(source_root, first)
                    if any(
                        alias.name not in public_exports and alias.name not in _PUBLIC_SKILL_SEAMS
                        for alias in node.names
                    ):
                        return True
            modules.append(node.module)
        for module in modules:
            parts = module.split(".")
            if len(parts) < 3 or parts[:2] != ["ai_video_platform", "skills"]:
                continue
            target_skill = parts[2]
            exposed_area = parts[3] if len(parts) > 3 else ""
            if target_skill != owner_skill and exposed_area not in _PUBLIC_SKILL_SEAMS:
                return True
            if target_skill != owner_skill and exposed_area == "" and isinstance(node, ast.ImportFrom):
                public_exports = _package_public_exports(source_root, target_skill)
                if any(
                    alias.name not in public_exports and alias.name not in _PUBLIC_SKILL_SEAMS
                    for alias in node.names
                ):
                    return True
    return False


_LIBRARY_MARKERS = {
    # Match both canonical roots and their short policy names.  The AST
    # scope analysis below ensures a marker is only actionable when it reaches
    # a write target in the same scope (or through a propagated helper).
    "product": ("ai video product library", "product library"),
    "research": ("ai video research library", "research library"),
}
_PATH_WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "touch", "unlink"}
_PATH_RELOCATION_METHODS = {"rename", "replace"}
_COPY_MOVE_FUNCTIONS = {"copy", "copy2", "copyfile", "copytree", "move"}
_PUBLIC_SKILL_SEAMS = {"", "interface", "public_api", "cli"}


class _ScopeCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.assignments: list[tuple[ast.expr, ast.expr]] = []
        self.calls: list[ast.Call] = []
        self.children: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda] = []
        self.module_aliases: dict[str, str] = {}
        self.function_aliases: dict[str, tuple[str, str]] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in {"os", "shutil"}:
                self.module_aliases[alias.asname or alias.name] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module not in {"os", "shutil"}:
            return
        for alias in node.names:
            self.function_aliases[alias.asname or alias.name] = (node.module, alias.name)

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
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        self.children.append(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for expression in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        self.children.append(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.children.append(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in (*node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        self.children.append(node)


def _binding_key(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        owner = _binding_key(target.value)
        return f"{owner}.{target.attr}" if owner else None
    return None


def _assigned_names(target: ast.expr) -> tuple[str, ...]:
    binding_key = _binding_key(target)
    if binding_key is not None:
        return (binding_key,)
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
        return frozenset(
            kind
            for kind, markers in _LIBRARY_MARKERS.items()
            if any(marker in lowered for marker in markers)
        )
    binding_key = _binding_key(expression) if isinstance(expression, (ast.Name, ast.Attribute)) else None
    if binding_key is not None:
        bound = bindings.get(binding_key, frozenset())
        if isinstance(expression, ast.Attribute):
            return bound | _expression_library_markers(expression.value, bindings)
        return bound
    if isinstance(expression, ast.Attribute):
        return _expression_library_markers(expression.value, bindings)
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
            _expression_library_markers(expression.func, bindings),
            *(_expression_library_markers(argument, bindings) for argument in expression.args),
            *(_expression_library_markers(item.value, bindings) for item in expression.keywords),
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


def _module_write_target_markers(
    module_name: str,
    function_name: str,
    call: ast.Call,
    bindings: dict[str, frozenset[str]],
) -> frozenset[str] | None:
    if module_name == "os":
        if function_name in {"mkdir", "makedirs", "remove", "unlink", "rmdir", "removedirs"}:
            targets = [
                *call.args[:1],
                *[item.value for item in call.keywords if item.arg in {"path", "name"}],
            ]
            return frozenset().union(
                *(_expression_library_markers(target, bindings) for target in targets)
            )
        if function_name in _PATH_RELOCATION_METHODS:
            targets = [
                *call.args[:2],
                *[item.value for item in call.keywords if item.arg in {"src", "dst"}],
            ]
            return frozenset().union(
                *(_expression_library_markers(target, bindings) for target in targets)
            )
    if module_name == "shutil" and function_name in _COPY_MOVE_FUNCTIONS:
        destinations = [
            *call.args[1:2],
            *[item.value for item in call.keywords if item.arg in {"dst", "destination"}],
        ]
        return frozenset().union(
            *(_expression_library_markers(target, bindings) for target in destinations)
        )
    return None


def _summary_target_markers(
    summary: tuple[tuple[str, ...], frozenset[str]],
    call: ast.Call,
    bindings: dict[str, frozenset[str]],
    *,
    bound_method: bool = False,
) -> frozenset[str]:
    parameters, written_parameters = summary
    positional_parameters = parameters[1:] if bound_method else parameters
    targets = [
        argument
        for parameter, argument in zip(positional_parameters, call.args)
        if parameter in written_parameters
    ]
    targets.extend(
        keyword.value
        for keyword in call.keywords
        if keyword.arg in written_parameters
    )
    return frozenset().union(
        *(_expression_library_markers(target, bindings) for target in targets)
    )


def _write_target_markers(
    call: ast.Call,
    bindings: dict[str, frozenset[str]],
    module_aliases: dict[str, str],
    function_aliases: dict[str, tuple[str, str]],
    callable_summaries: dict[str, tuple[tuple[str, ...], frozenset[str]]],
) -> frozenset[str]:
    function = call.func
    if isinstance(function, ast.Attribute):
        if (
            isinstance(function.value, ast.Name)
            and function.value.id in {"self", "cls"}
            and function.attr in callable_summaries
        ):
            return _summary_target_markers(
                callable_summaries[function.attr],
                call,
                bindings,
                bound_method=True,
            )
        supplied_module_name = function.value.id if isinstance(function.value, ast.Name) else None
        module_name = module_aliases.get(supplied_module_name, supplied_module_name)
        module_markers = _module_write_target_markers(module_name or "", function.attr, call, bindings)
        if module_markers is not None:
            return module_markers
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
        aliased_function = function_aliases.get(function.id)
        if aliased_function is not None:
            module_markers = _module_write_target_markers(*aliased_function, call, bindings)
            if module_markers is not None:
                return module_markers
        summary = callable_summaries.get(function.id)
        if summary is not None:
            return _summary_target_markers(summary, call, bindings)
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


def _resolved_scope_bindings(
    assignments: Iterable[tuple[ast.expr, ast.expr]],
    inherited_bindings: dict[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    assignment_list = tuple(assignments)
    local_names = {
        name
        for target, _ in assignment_list
        for name in _assigned_names(target)
    }
    bindings = {
        name: markers
        for name, markers in inherited_bindings.items()
        if name not in local_names
    }
    bindings.update((name, frozenset()) for name in local_names)
    for _ in range(len(assignment_list) + 1):
        changed = False
        for target, value in assignment_list:
            markers = _expression_library_markers(value, bindings)
            for name in _assigned_names(target):
                combined = bindings.get(name, frozenset()) | markers
                if combined != bindings.get(name, frozenset()):
                    bindings[name] = combined
                    changed = True
        if not changed:
            break
    return bindings


def _callable_scope_bindings(
    scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    inherited_bindings: dict[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    bindings = dict(inherited_bindings)
    positional = [*scope.args.posonlyargs, *scope.args.args]
    parameters = [*positional, *scope.args.kwonlyargs]
    if scope.args.vararg is not None:
        parameters.append(scope.args.vararg)
    if scope.args.kwarg is not None:
        parameters.append(scope.args.kwarg)
    bindings.update((parameter.arg, frozenset()) for parameter in parameters)

    positional_defaults = zip(positional[-len(scope.args.defaults) :], scope.args.defaults)
    keyword_defaults = (
        (parameter, default)
        for parameter, default in zip(scope.args.kwonlyargs, scope.args.kw_defaults)
        if default is not None
    )
    for parameter, default in (*positional_defaults, *keyword_defaults):
        bindings[parameter.arg] = _expression_library_markers(default, inherited_bindings)
    return bindings


def _callable_write_summary(
    scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    inherited_module_aliases: dict[str, str],
    inherited_function_aliases: dict[str, tuple[str, str]],
    callable_summaries: dict[str, tuple[tuple[str, ...], frozenset[str]]],
) -> tuple[tuple[str, ...], frozenset[str]]:
    collector = _ScopeCollector()
    if isinstance(scope, ast.Lambda):
        collector.visit(scope.body)
    else:
        for statement in scope.body:
            collector.visit(statement)
    positional = [*scope.args.posonlyargs, *scope.args.args]
    parameters = [*positional, *scope.args.kwonlyargs]
    if scope.args.vararg is not None:
        parameters.append(scope.args.vararg)
    if scope.args.kwarg is not None:
        parameters.append(scope.args.kwarg)
    parameter_names = tuple(parameter.arg for parameter in parameters)
    symbolic_bindings = {
        name: frozenset({f"parameter:{name}"})
        for name in parameter_names
    }
    bindings = _resolved_scope_bindings(collector.assignments, symbolic_bindings)
    local_names = {
        name
        for target, _ in collector.assignments
        for name in _assigned_names(target)
    }
    module_aliases = {
        name: module
        for name, module in inherited_module_aliases.items()
        if name not in local_names
    }
    module_aliases.update(collector.module_aliases)
    function_aliases = {
        name: target
        for name, target in inherited_function_aliases.items()
        if name not in local_names
    }
    function_aliases.update(collector.function_aliases)
    writes = frozenset().union(
        *(
            _write_target_markers(
                call,
                bindings,
                module_aliases,
                function_aliases,
                callable_summaries,
            )
            for call in collector.calls
        )
    )
    written_parameters = frozenset(
        marker.removeprefix("parameter:")
        for marker in writes
        if marker.startswith("parameter:")
    )
    return parameter_names, written_parameters


def _callable_write_summaries(
    collector: _ScopeCollector,
    module_aliases: dict[str, str],
    function_aliases: dict[str, tuple[str, str]],
) -> dict[str, tuple[tuple[str, ...], frozenset[str]]]:
    candidates: dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda] = {
        child.name: child
        for child in collector.children
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    candidates.update(
        (name, value)
        for target, value in collector.assignments
        if isinstance(value, ast.Lambda)
        for name in _assigned_names(target)
        if "." not in name
    )
    summaries: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {}
    for _ in range(len(candidates) + 1):
        updated = {
            name: _callable_write_summary(
                candidate,
                module_aliases,
                function_aliases,
                summaries,
            )
            for name, candidate in candidates.items()
        }
        if updated == summaries:
            break
        summaries = updated
    return summaries


def _scope_library_writes(
    scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda,
    inherited_bindings: dict[str, frozenset[str]],
    inherited_module_aliases: dict[str, str],
    inherited_function_aliases: dict[str, tuple[str, str]],
) -> frozenset[str]:
    collector = _ScopeCollector()
    if isinstance(scope, ast.Lambda):
        collector.visit(scope.body)
    else:
        for statement in scope.body:
            collector.visit(statement)
    scope_bindings = (
        _callable_scope_bindings(scope, inherited_bindings)
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        else inherited_bindings
    )
    bindings = _resolved_scope_bindings(collector.assignments, scope_bindings)
    local_names = {
        name
        for target, _ in collector.assignments
        for name in _assigned_names(target)
    }
    module_aliases = {
        name: module
        for name, module in inherited_module_aliases.items()
        if name not in local_names
    }
    module_aliases.update(collector.module_aliases)
    function_aliases = {
        name: target
        for name, target in inherited_function_aliases.items()
        if name not in local_names
    }
    function_aliases.update(collector.function_aliases)
    callable_summaries = _callable_write_summaries(
        collector,
        module_aliases,
        function_aliases,
    )
    writes = frozenset().union(
        *(
            _write_target_markers(
                call,
                bindings,
                module_aliases,
                function_aliases,
                callable_summaries,
            )
            for call in collector.calls
        )
    )
    child_bindings = bindings
    if isinstance(scope, ast.ClassDef):
        instance_assignments: list[tuple[ast.expr, ast.expr]] = []
        for child in collector.children:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            child_collector = _ScopeCollector()
            for statement in child.body:
                child_collector.visit(statement)
            instance_assignments.extend(
                (target, value)
                for target, value in child_collector.assignments
                if any("." in name for name in _assigned_names(target))
            )
        child_bindings = _resolved_scope_bindings(instance_assignments, bindings)
    for child in collector.children:
        writes |= _scope_library_writes(
            child,
            child_bindings,
            module_aliases,
            function_aliases,
        )
    return writes


def _library_writes(tree: ast.Module) -> frozenset[str]:
    return _scope_library_writes(tree, {}, {}, {})


def _forbidden_runtime_import(tree: ast.AST, relative: Path) -> str | None:
    relative_path = relative.as_posix()
    if (
        relative_path.endswith("core/guards.py")
        or relative_path in _AUTHORIZED_PROVIDER_NETWORK_ADAPTERS
    ):
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
        if _cross_skill_imports(tree, owner_skill, source_root):
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
