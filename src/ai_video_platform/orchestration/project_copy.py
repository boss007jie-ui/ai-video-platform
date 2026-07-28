"""Offline inspection and selective copying of completed video projects."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys


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
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_COPY_REQUEST_FIELDS = frozenset({
    "source_project",
    "destination_project",
    "project_id",
    "inventory_digest",
    "selected_candidate_ids",
})
_REMOVED_SCRIPT_KEYS = frozenset({
    "approval_record",
    "approval_status",
    "approved_by",
    "artifact_id",
    "authorization_id",
    "contract_id",
    "contract_identity",
    "idempotency_key",
    "payload_digest",
    "producer",
    "source_contract_ids",
    "source_hashes",
    "source_provenance",
    "task_id",
})
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


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ProjectCopyError("project copy arguments are invalid")


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


def _format_time(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sanitize_script(value: object, *, top_level: bool = False) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_script(item)
            for key, item in value.items()
            if key not in _REMOVED_SCRIPT_KEYS and not (top_level and key == "status")
        }
    if isinstance(value, list):
        return [_sanitize_script(item) for item in value]
    return value


def _verified_source_bytes(source: Path, record: Mapping[str, object]) -> bytes:
    content = source.read_bytes()
    if len(content) != record.get("size_bytes") or _content_digest(content) != record.get("sha256"):
        raise ProjectCopyError("source project changed after inspection")
    return content


def copy_project(
    request: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    if set(request) != _COPY_REQUEST_FIELDS:
        raise ProjectCopyError("project copy request fields are invalid")
    source_value = request.get("source_project")
    destination_value = request.get("destination_project")
    project_id = request.get("project_id")
    inventory_digest = request.get("inventory_digest")
    selected_ids = request.get("selected_candidate_ids")
    if not isinstance(source_value, str) or not source_value:
        raise ProjectCopyError("source_project is invalid")
    if not isinstance(destination_value, str) or not destination_value:
        raise ProjectCopyError("destination_project is invalid")
    if not isinstance(project_id, str) or _PROJECT_ID.fullmatch(project_id) is None:
        raise ProjectCopyError("project_id is invalid")
    if not isinstance(inventory_digest, str) or not inventory_digest:
        raise ProjectCopyError("inventory_digest is invalid")
    if (
        not isinstance(selected_ids, list)
        or any(not isinstance(item, str) or not item for item in selected_ids)
        or len(set(selected_ids)) != len(selected_ids)
    ):
        raise ProjectCopyError("selected_candidate_ids is invalid")

    inventory = inspect_project(source_value)
    if inventory["inventory_digest"] != inventory_digest:
        raise ProjectCopyError("source project changed after inspection")
    source_path = Path(str(inventory["source_project"]))
    supplied_destination = Path(destination_value)
    if supplied_destination.is_symlink() or supplied_destination.exists():
        raise ProjectCopyError("destination project already exists")
    destination = supplied_destination.resolve(strict=False)
    if destination.is_relative_to(source_path):
        raise ProjectCopyError("destination project must be outside the source project")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ProjectCopyError("destination project parent is invalid")

    raw_assets = inventory.get("assets")
    if not isinstance(raw_assets, Mapping):
        raise ProjectCopyError("project inventory is invalid")
    candidate_by_id: dict[str, Mapping[str, object]] = {}
    for role in ASSET_ROLES:
        group = raw_assets.get(role)
        if not isinstance(group, list):
            raise ProjectCopyError("project inventory is invalid")
        for item in group:
            if not isinstance(item, Mapping) or not isinstance(item.get("candidate_id"), str):
                raise ProjectCopyError("project inventory is invalid")
            candidate_by_id[str(item["candidate_id"])] = item
    unknown = set(selected_ids).difference(candidate_by_id)
    if unknown:
        raise ProjectCopyError("selected asset is not in the inspected project")

    destination.mkdir()
    try:
        script_records: list[dict[str, object]] = []
        raw_scripts = inventory.get("scripts")
        if not isinstance(raw_scripts, list):
            raise ProjectCopyError("project inventory is invalid")
        for item in raw_scripts:
            if not isinstance(item, Mapping) or not isinstance(item.get("relative_path"), str):
                raise ProjectCopyError("project inventory is invalid")
            relative = Path(str(item["relative_path"]))
            content = _verified_source_bytes(source_path / relative, item)
            copied_relative = Path("reuse_source") / "scripts" / relative
            copied_path = destination / copied_relative
            copied_path.parent.mkdir(parents=True, exist_ok=True)
            if relative.suffix.lower() == ".json":
                try:
                    parsed = json.loads(content.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise ProjectCopyError("reusable script JSON is invalid") from None
                envelope = {
                    "schema_version": SCHEMA_VERSION,
                    "document_type": "project-copy-draft-script-v1",
                    "source_relative_path": relative.as_posix(),
                    "content": _sanitize_script(parsed, top_level=True),
                }
                copied_content = (_canonical_json(envelope) + "\n").encode("utf-8")
            else:
                copied_content = content
            copied_path.write_bytes(copied_content)
            script_records.append({
                "source_relative_path": relative.as_posix(),
                "copied_relative_path": copied_relative.as_posix(),
                "source_size_bytes": len(content),
                "source_sha256": _content_digest(content),
                "copied_size_bytes": len(copied_content),
                "copied_sha256": _content_digest(copied_content),
            })

        asset_records: list[dict[str, object]] = []
        for candidate_id in sorted(selected_ids):
            item = candidate_by_id[candidate_id]
            relative = Path(str(item["relative_path"]))
            content = _verified_source_bytes(source_path / relative, item)
            role = str(item["role"])
            digest_hex = str(item["sha256"]).removeprefix("sha256:")
            copied_relative = Path("reuse_source") / "assets" / role / f"{digest_hex}-{relative.name}"
            copied_path = destination / copied_relative
            copied_path.parent.mkdir(parents=True, exist_ok=True)
            copied_path.write_bytes(content)
            if _content_digest(copied_path.read_bytes()) != item["sha256"]:
                raise ProjectCopyError("copied asset integrity check failed")
            asset_records.append({
                "candidate_id": candidate_id,
                "role": role,
                "source_relative_path": relative.as_posix(),
                "copied_relative_path": copied_relative.as_posix(),
                "size_bytes": len(content),
                "sha256": str(item["sha256"]),
            })

        manifest: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
            "source_project": str(source_path),
            "created_at": _format_time(now),
            "status": "draft",
            "inventory_digest": inventory_digest,
            "scripts": script_records,
            "assets": asset_records,
        }
        (destination / "PROJECT_COPY.json").write_text(
            _canonical_json(manifest) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return manifest
    except Exception as error:
        shutil.rmtree(destination)
        if isinstance(error, ProjectCopyError):
            raise
        raise ProjectCopyError("project copy failed") from None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="project-copy")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--source", required=True)
    copy = subparsers.add_parser("copy")
    copy.add_argument("--request", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        if args.operation == "inspect":
            result = inspect_project(args.source)
        else:
            raw = sys.stdin.read() if args.request == "-" else Path(args.request).read_text(encoding="utf-8")
            request = json.loads(raw)
            if not isinstance(request, Mapping):
                raise ProjectCopyError("project copy request must be a JSON object")
            result = copy_project(request)
        response: dict[str, object] = {"ok": True, "result": result}
        exit_code = 0
    except ProjectCopyError as error:
        response = {"ok": False, "error": str(error)}
        exit_code = 2
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        response = {"ok": False, "error": "project copy input is invalid"}
        exit_code = 2
    print(_canonical_json(response))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
