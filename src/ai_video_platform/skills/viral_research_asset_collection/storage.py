"""Controlled Research Library storage seams with offline adapters."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from .errors import ErrorCode, SkillError


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _canonical(record: Mapping[str, object]) -> bytes:
    return json.dumps(dict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(record: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(record)).hexdigest()


def _assert_record(record: Mapping[str, object]) -> str:
    source_id = record.get("source_id")
    if not isinstance(source_id, str) or not _SAFE_ID.fullmatch(source_id):
        raise SkillError(ErrorCode.PATH_FORBIDDEN, "source_id is not path-safe", field_paths=("source_id",))
    required = ("source_url", "lifecycle_state", "rights_status", "pii_detected", "expires_at")
    missing = tuple(name for name in required if name not in record)
    if missing:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Research record is incomplete", field_paths=missing)
    return source_id


def _retention_was_extended(existing: Mapping[str, object], incoming: Mapping[str, object]) -> bool:
    old = existing.get("retention_until")
    new = incoming.get("retention_until")
    return isinstance(old, str) and isinstance(new, str) and new > old


class InMemoryResearchLibraryAdapter:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}
        self.quarantine: dict[str, dict[str, object]] = {}
        self.audit_log: list[dict[str, object]] = []
        self._idempotency: dict[str, str] = {}

    def write_record(self, record: Mapping[str, object], *, idempotency_key: str) -> None:
        source_id = _assert_record(record)
        snapshot = dict(record)
        digest = _digest(snapshot)
        previous_digest = self._idempotency.get(idempotency_key)
        if previous_digest is not None:
            if previous_digest != digest:
                raise SkillError(ErrorCode.IDEMPOTENCY_CONFLICT, "Idempotency key already has different content")
            return
        existing = self.records.get(source_id) or self.quarantine.get(source_id)
        if existing is not None and _retention_was_extended(existing, snapshot):
            raise SkillError(
                ErrorCode.RETENTION_EXTENSION_FORBIDDEN,
                "Retention cannot be silently extended",
                field_paths=("retention_until",),
            )
        target = self.quarantine if snapshot["lifecycle_state"] == "quarantined" else self.records
        target[source_id] = snapshot
        self._idempotency[idempotency_key] = digest
        self.audit_log.append({"action": "written", "source_id": source_id, "digest": digest})

    def delete_record(self, source_id: str, *, reason: str) -> None:
        existed = self.records.pop(source_id, None)
        if existed is None:
            existed = self.quarantine.pop(source_id, None)
        self.audit_log.append({"action": "deleted", "source_id": source_id, "reason": reason, "existed": existed is not None})


class ResearchLibraryAdapter:
    """Filesystem metadata writer; callers supply an explicitly authorized root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        if self.root.is_symlink():
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research Library root cannot be a symlink")
        for relative in ("metadata", "quarantine", "audit"):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self._memory = InMemoryResearchLibraryAdapter()

    @property
    def audit_log(self) -> list[dict[str, object]]:
        return self._memory.audit_log

    def _target(self, source_id: str, *, quarantined: bool) -> Path:
        folder = self.root / ("quarantine" if quarantined else "metadata")
        target = folder / f"{source_id}.json"
        if folder.is_symlink() or target.is_symlink() or target.parent.resolve() != folder.resolve():
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research Library path escaped its controlled root")
        return target

    def write_record(self, record: Mapping[str, object], *, idempotency_key: str) -> None:
        source_id = _assert_record(record)
        self._memory.write_record(record, idempotency_key=idempotency_key)
        target = self._target(source_id, quarantined=record["lifecycle_state"] == "quarantined")
        payload = _canonical(record)
        if target.exists() and target.read_bytes() == payload:
            return
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{source_id}-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def delete_record(self, source_id: str, *, reason: str) -> None:
        if not _SAFE_ID.fullmatch(source_id):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "source_id is not path-safe")
        for quarantined in (False, True):
            target = self._target(source_id, quarantined=quarantined)
            if target.exists():
                target.unlink()
        self._memory.delete_record(source_id, reason=reason)
        audit_path = self.root / "audit" / "deletions.jsonl"
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"source_id": source_id, "reason": reason}, sort_keys=True) + "\n")
