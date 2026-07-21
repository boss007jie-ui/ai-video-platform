"""Task-workspace CLI ledger for cross-process replay and coarse concurrency."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ai_video_platform.contracts import parse_json_object
from ai_video_platform.core.guards import LegacyPathGuard

from .errors import ImagePanelError, ImagePanelErrorCode


_LEDGER_NAME = ".image-panel-generation-ledger.json"
_FORBIDDEN_WORKSPACE_NAMES = {"ai video product library", "ai video research library"}


def assert_task_workspace(path: Path) -> Path:
    resolved = LegacyPathGuard().assert_allowed(path.resolve())
    lowered_parts = {part.casefold() for part in resolved.parts}
    if lowered_parts & _FORBIDDEN_WORKSPACE_NAMES:
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "CLI task workspace cannot be a Product or Research Library",
            category="authorization",
            field_paths=("input",),
        )
    return resolved


class CliExecutionLedger:
    def __init__(self, workspace: Path) -> None:
        self._workspace = assert_task_workspace(workspace)
        self._path = self._workspace / _LEDGER_NAME
        self._lock_path = self._workspace / f"{_LEDGER_NAME}.lock"
        self._lock_fd: int | None = None
        self._document: dict[str, Any] = {"schema_version": "1.0", "records": {}}

    def begin(self, key: str, request_hash: str) -> dict[str, Any] | None:
        try:
            self._lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ImagePanelError(
                ImagePanelErrorCode.IDEMPOTENCY_IN_PROGRESS,
                "Another CLI generation is active in this task workspace",
                category="state",
                retryable=True,
            ) from exc
        if self._path.exists():
            self._document = parse_json_object(self._path.read_bytes())
        records = self._document.get("records")
        if not isinstance(records, dict):
            self.abort()
            raise ImagePanelError(
                ImagePanelErrorCode.CONTRACT_INVALID,
                "CLI ledger is malformed",
                category="state",
            )
        existing = records.get(key)
        if existing is None:
            return None
        if not isinstance(existing, dict) or existing.get("request_hash") != request_hash:
            self.abort()
            raise ImagePanelError(
                ImagePanelErrorCode.IDEMPOTENCY_CONFLICT,
                "CLI idempotency key was reused with a different request hash",
                category="conflict",
                field_paths=("idempotency_key", "request_hash"),
            )
        outcome = existing.get("outcome")
        self.abort()
        if not isinstance(outcome, dict):
            raise ImagePanelError(
                ImagePanelErrorCode.CONTRACT_INVALID,
                "CLI ledger outcome is malformed",
                category="state",
            )
        replay = dict(outcome)
        replay["replayed"] = True
        return replay

    def commit(self, key: str, request_hash: str, outcome: dict[str, Any]) -> None:
        records = self._document.setdefault("records", {})
        records[key] = {"request_hash": request_hash, "outcome": outcome}
        temp_path = self._workspace / f"{_LEDGER_NAME}.{os.getpid()}.tmp"
        try:
            with temp_path.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(self._document, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self._path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
            self.abort()

    def abort(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            pass
