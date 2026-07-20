"""Path-safe atomic artifact writer for Reference Analysis task outputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import tempfile

from .errors import ErrorCode, SkillError


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", lambda: False)
    try:
        return path.is_symlink() or bool(is_junction())
    except OSError:
        return True


def _assert_no_links(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if _is_link(current):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Artifact path contains a link or reparse point")


def canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SafeArtifactWriter:
    def __init__(self, workspace: Path) -> None:
        supplied = Path(os.path.abspath(os.fspath(workspace)))
        _assert_no_links(supplied)
        if not supplied.is_dir():
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Task workspace must already exist and be a directory")
        self.workspace = supplied.resolve()

    def _target(self, output_path: str) -> Path:
        relative = Path(output_path)
        if not output_path or relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Output path must be a safe relative path", field_paths=("output_path",))
        target = self.workspace / relative
        current = self.workspace
        for part in relative.parts[:-1]:
            current /= part
            if _is_link(current):
                raise SkillError(ErrorCode.PATH_FORBIDDEN, "Output parent cannot be a link")
            current.mkdir(exist_ok=True)
            if _is_link(current):
                raise SkillError(ErrorCode.PATH_FORBIDDEN, "Output parent cannot be a link")
        _assert_no_links(target.parent)
        if _is_link(target) or target.parent.resolve() != current.resolve():
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Output escaped the task workspace")
        try:
            if os.path.commonpath((os.fspath(self.workspace), os.fspath(target.parent.resolve()))) != os.fspath(self.workspace):
                raise SkillError(ErrorCode.PATH_FORBIDDEN, "Output escaped the task workspace")
        except ValueError as exc:
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Output escaped the task workspace") from exc
        return target

    def write(
        self,
        artifact: Mapping[str, object],
        *,
        output_path: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        target = self._target(output_path)
        payload = canonical_json(artifact)
        if target.exists():
            if target.read_bytes() == payload:
                return Path(output_path).as_posix()
            raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Output path already contains different content")
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if cancelled and cancelled():
                raise SkillError(ErrorCode.CANCELLED, "Reference analysis was cancelled")
            if _is_link(target) or _is_link(target.parent):
                raise SkillError(ErrorCode.PATH_FORBIDDEN, "Output path changed to a link")
            os.replace(temp_name, target)
        except SkillError:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        except Exception as exc:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise SkillError(ErrorCode.WRITE_FAILED, "Atomic artifact write failed") from exc
        return Path(output_path).as_posix()
