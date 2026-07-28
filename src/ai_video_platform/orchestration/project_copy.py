"""Offline inspection and selective copying of completed video projects."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re


SCHEMA_VERSION = "1.0.0"
SCRIPT_NAMES = frozenset({
    "production_storyboard_plan.json",
    "production_storyboard_panel_plan.json",
    "STORYBOARD_HUMAN.md",
    "CTA_OPTIONS.md",
})
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
ASSET_ROLES = ("character", "scene", "product", "storyboard_panel", "other_reference")
_PANEL_NAME = re.compile(r"^s\d+(?:-detail)?-p\d+$", re.IGNORECASE)
_EXCLUDED_DIRECTORIES = frozenset({
    ".hermes",
    "audit",
    "evidence",
    "failures",
    "logs",
    "output",
    "qa",
    "qa_review",
    "review",
})


class ProjectCopyError(ValueError):
    """Stable rejection raised at the project-copy boundary."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def _content_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _is_excluded_directory(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in _EXCLUDED_DIRECTORIES
        or lowered.startswith("deliverables_rejected")
        or "superseded" in lowered
    )


def _iter_project_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for root, directory_names, file_names in os.walk(source, topdown=True, followlinks=False):
        root_path = Path(root)
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = root_path / name
            if candidate.is_symlink():
                raise ProjectCopyError("source project contains a symlink")
            if not _is_excluded_directory(name):
                retained_directories.append(name)
        directory_names[:] = retained_directories
        for name in sorted(file_names):
            candidate = root_path / name
            if candidate.is_symlink():
                raise ProjectCopyError("source project contains a symlink")
            if candidate.is_file():
                files.append(candidate)
    return files


def _asset_role(path: Path) -> str:
    stem = path.stem.lower()
    if stem.startswith("character-anchor-"):
        return "character"
    if stem.startswith("scene-anchor-"):
        return "scene"
    if _PANEL_NAME.fullmatch(stem) is not None:
        return "storyboard_panel"
    if any(part.lower() in {"refs", "input"} for part in path.parts):
        return "product"
    return "other_reference"


def _asset_priority(relative_path: Path) -> tuple[int, str]:
    parts = {part.lower() for part in relative_path.parts}
    if "deliverables" in parts:
        rank = 0
    elif "refs" in parts:
        rank = 1
    elif "input" in parts:
        rank = 2
    else:
        rank = 3
    return rank, relative_path.as_posix().lower()


def inspect_project(source: Path | str) -> dict[str, object]:
    supplied = Path(source)
    if supplied.is_symlink():
        raise ProjectCopyError("source project must not be a symlink")
    try:
        source_path = supplied.resolve(strict=True)
    except OSError:
        raise ProjectCopyError("source project is unavailable") from None
    if not source_path.is_dir():
        raise ProjectCopyError("source project must be a directory")

    scripts: list[dict[str, object]] = []
    discovered_assets: list[tuple[tuple[int, str], str, dict[str, object]]] = []
    for path in _iter_project_files(source_path):
        relative = path.relative_to(source_path)
        if path.name in SCRIPT_NAMES:
            content = path.read_bytes()
            scripts.append({
                "relative_path": relative.as_posix(),
                "size_bytes": len(content),
                "sha256": _content_digest(content),
            })
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if path.name.lower().startswith("storyboard_master_sheet_"):
            continue
        content = path.read_bytes()
        digest = _content_digest(content)
        role = _asset_role(relative)
        item = {
            "candidate_id": f"asset:{role}:{digest.removeprefix('sha256:')}",
            "role": role,
            "relative_path": relative.as_posix(),
            "size_bytes": len(content),
            "sha256": digest,
        }
        discovered_assets.append((_asset_priority(relative), digest, item))

    if not scripts:
        raise ProjectCopyError("source project has no reusable script")
    scripts.sort(key=lambda item: str(item["relative_path"]))
    selected_by_digest: dict[str, tuple[tuple[int, str], dict[str, object]]] = {}
    for priority, digest, item in discovered_assets:
        current = selected_by_digest.get(digest)
        if current is None or priority < current[0]:
            selected_by_digest[digest] = (priority, item)
    assets: dict[str, list[dict[str, object]]] = {role: [] for role in ASSET_ROLES}
    for _, item in sorted(selected_by_digest.values(), key=lambda value: str(value[1]["candidate_id"])):
        assets[str(item["role"])].append(item)

    inventory: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source_project": str(source_path),
        "scripts": scripts,
        "assets": assets,
    }
    inventory["inventory_digest"] = _content_digest(_canonical_json(inventory).encode("utf-8"))
    return inventory
