"""Controlled Research Library storage seams with offline adapters."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
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


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", lambda: False)
    try:
        return path.is_symlink() or bool(is_junction())
    except OSError:
        return True


def _assert_no_link_components(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if _is_link(current):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research Library path contains a link or reparse point")


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_create(path: Path, payload: bytes) -> None:
    """Publish bytes only if the destination is still absent."""
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


@contextmanager
def _exclusive_source_lock(path: Path):
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SkillError(ErrorCode.STORAGE_CONFLICT, "A writer already owns this source identity") from exc
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class InMemoryResearchLibraryAdapter:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}
        self.quarantine: dict[str, dict[str, object]] = {}
        self.audit_log: list[dict[str, object]] = []
        self._idempotency: dict[str, str] = {}
        self._requests: dict[str, dict[str, object]] = {}
        self._request_lock = Lock()

    def begin_request(self, operation: str, idempotency_key: str, request_digest: str) -> Mapping[str, object] | None:
        with self._request_lock:
            existing = self._requests.get(idempotency_key)
            if existing is None:
                self._requests[idempotency_key] = {
                    "operation": operation, "request_digest": request_digest, "status": "IN_PROGRESS",
                }
                return None
            if existing.get("operation") != operation or existing.get("request_digest") != request_digest:
                raise SkillError(ErrorCode.IDEMPOTENCY_CONFLICT, "Idempotency key already belongs to a different request")
            if existing.get("status") == "COMPLETED" and isinstance(existing.get("result"), Mapping):
                return deepcopy(dict(existing["result"]))
            raise SkillError(ErrorCode.IDEMPOTENCY_CONFLICT, "Idempotent request is already in progress")

    def complete_request(
        self, operation: str, idempotency_key: str, request_digest: str, result: Mapping[str, object],
    ) -> None:
        with self._request_lock:
            existing = self._requests.get(idempotency_key)
            if existing is None or existing.get("operation") != operation or existing.get("request_digest") != request_digest:
                raise SkillError(ErrorCode.IDEMPOTENCY_CONFLICT, "Request claim does not match completion")
            self._requests[idempotency_key] = {
                "operation": operation, "request_digest": request_digest, "status": "COMPLETED",
                "result": deepcopy(dict(result)),
            }

    def abort_request(self, operation: str, idempotency_key: str, request_digest: str) -> None:
        with self._request_lock:
            existing = self._requests.get(idempotency_key)
            if (
                existing is not None
                and existing.get("operation") == operation
                and existing.get("request_digest") == request_digest
                and existing.get("status") == "IN_PROGRESS"
            ):
                del self._requests[idempotency_key]

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
        if existing is not None and _digest(existing) != digest:
            raise SkillError(ErrorCode.STORAGE_CONFLICT, "Existing research record has different content")
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
        supplied_root = Path(os.path.abspath(os.fspath(root)))
        _assert_no_link_components(supplied_root)
        if supplied_root.exists() and _is_link(supplied_root):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research Library root cannot be a symlink")
        supplied_root.mkdir(parents=True, exist_ok=True)
        if _is_link(supplied_root):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research Library root cannot be a symlink")
        self.root = supplied_root.resolve()
        for relative in ("metadata", "quarantine", "audit"):
            path = self.root / relative
            if path.exists() and _is_link(path):
                raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research Library subdirectory cannot be a symlink")
            path.mkdir(parents=True, exist_ok=True)
            if _is_link(path):
                raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research Library subdirectory cannot be a symlink")
        self._request_root = self.root / "audit" / "requests"
        if self._request_root.exists() and _is_link(self._request_root):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Request ledger directory cannot be a symlink")
        self._request_root.mkdir(parents=True, exist_ok=True)
        if _is_link(self._request_root):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Request ledger directory cannot be a symlink")
        self._source_lock_root = self.root / "audit" / "source-locks"
        if self._source_lock_root.exists() and _is_link(self._source_lock_root):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Source lock directory cannot be a symlink")
        self._source_lock_root.mkdir(parents=True, exist_ok=True)
        if _is_link(self._source_lock_root):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Source lock directory cannot be a symlink")
        self._memory = InMemoryResearchLibraryAdapter()
        self._ledger_path = self.root / "audit" / "idempotency.json"
        self._audit_index_path = self.root / "audit" / "lifecycle-index.json"
        self._lifecycle_path = self.root / "audit" / "lifecycle.jsonl"
        self._assert_audit_path(self._ledger_path)
        self._assert_audit_path(self._audit_index_path)
        self._assert_audit_path(self._lifecycle_path)
        if self._ledger_path.exists():
            try:
                loaded = json.loads(self._ledger_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SkillError(ErrorCode.STORAGE_CONFLICT, "Idempotency ledger is unreadable") from exc
            if not isinstance(loaded, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in loaded.items()):
                raise SkillError(ErrorCode.STORAGE_CONFLICT, "Idempotency ledger is invalid")
            self._ledger: dict[str, str] = loaded
        else:
            self._ledger = {}
        if self._audit_index_path.exists():
            try:
                audit_loaded = json.loads(self._audit_index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SkillError(ErrorCode.STORAGE_CONFLICT, "Lifecycle audit index is unreadable") from exc
            if not isinstance(audit_loaded, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in audit_loaded.items()):
                raise SkillError(ErrorCode.STORAGE_CONFLICT, "Lifecycle audit index is invalid")
            self._audit_index: dict[str, str] = audit_loaded
        else:
            self._audit_index = {}

    @property
    def audit_log(self) -> list[dict[str, object]]:
        return self._memory.audit_log

    def _target(self, source_id: str, *, quarantined: bool) -> Path:
        folder = self.root / ("quarantine" if quarantined else "metadata")
        target = folder / f"{source_id}.json"
        _assert_no_link_components(folder)
        if _is_link(folder) or _is_link(target) or target.parent.resolve() != folder.resolve():
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research Library path escaped its controlled root")
        return target

    def _assert_audit_path(self, path: Path) -> None:
        audit = self.root / "audit"
        _assert_no_link_components(audit)
        if _is_link(audit) or _is_link(path) or path.parent.resolve() != audit.resolve():
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research Library audit path escaped its controlled root")

    def _request_target(self, idempotency_key: str) -> Path:
        filename = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest() + ".json"
        target = self._request_root / filename
        _assert_no_link_components(self._request_root)
        if _is_link(self._request_root) or _is_link(target) or target.parent.resolve() != self._request_root.resolve():
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Request ledger path escaped its controlled root")
        return target

    def _source_lock_target(self, source_id: str) -> Path:
        target = self._source_lock_root / f"{source_id}.lock"
        _assert_no_link_components(self._source_lock_root)
        if _is_link(self._source_lock_root) or _is_link(target) or target.parent.resolve() != self._source_lock_root.resolve():
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Source lock path escaped its controlled root")
        return target

    @staticmethod
    def _read_request(target: Path) -> dict[str, object]:
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillError(ErrorCode.STORAGE_CONFLICT, "Request ledger entry is unreadable") from exc
        if not isinstance(value, dict):
            raise SkillError(ErrorCode.STORAGE_CONFLICT, "Request ledger entry is invalid")
        return value

    def begin_request(self, operation: str, idempotency_key: str, request_digest: str) -> Mapping[str, object] | None:
        target = self._request_target(idempotency_key)
        claim = {"operation": operation, "request_digest": request_digest, "status": "IN_PROGRESS"}
        try:
            _atomic_create(target, _canonical(claim))
            return None
        except FileExistsError:
            existing = self._read_request(target)
        if existing.get("operation") != operation or existing.get("request_digest") != request_digest:
            raise SkillError(ErrorCode.IDEMPOTENCY_CONFLICT, "Idempotency key already belongs to a different request")
        if existing.get("status") == "COMPLETED" and isinstance(existing.get("result"), Mapping):
            return deepcopy(dict(existing["result"]))
        raise SkillError(ErrorCode.IDEMPOTENCY_CONFLICT, "Idempotent request is already in progress")

    def complete_request(
        self, operation: str, idempotency_key: str, request_digest: str, result: Mapping[str, object],
    ) -> None:
        target = self._request_target(idempotency_key)
        existing = self._read_request(target)
        if existing.get("operation") != operation or existing.get("request_digest") != request_digest:
            raise SkillError(ErrorCode.IDEMPOTENCY_CONFLICT, "Request claim does not match completion")
        completed = {
            "operation": operation, "request_digest": request_digest, "status": "COMPLETED",
            "result": deepcopy(dict(result)),
        }
        _atomic_write(target, _canonical(completed))

    def abort_request(self, operation: str, idempotency_key: str, request_digest: str) -> None:
        target = self._request_target(idempotency_key)
        if not target.exists():
            return
        existing = self._read_request(target)
        if (
            existing.get("operation") == operation
            and existing.get("request_digest") == request_digest
            and existing.get("status") == "IN_PROGRESS"
        ):
            target.unlink()

    def _persist_ledger(self) -> None:
        self._assert_audit_path(self._ledger_path)
        _atomic_write(self._ledger_path, _canonical(self._ledger))

    def _append_lifecycle(self, event: Mapping[str, object]) -> None:
        self._assert_audit_path(self._lifecycle_path)
        with self._lifecycle_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _ensure_lifecycle_event(self, idempotency_key: str, source_id: str, digest: str) -> None:
        existing = self._audit_index.get(idempotency_key)
        if existing is not None:
            if existing != digest:
                raise SkillError(ErrorCode.IDEMPOTENCY_CONFLICT, "Lifecycle audit key has different content")
            return
        self._append_lifecycle({"action": "written", "source_id": source_id, "digest": digest, "idempotency_key": idempotency_key})
        self._audit_index[idempotency_key] = digest
        self._assert_audit_path(self._audit_index_path)
        _atomic_write(self._audit_index_path, _canonical(self._audit_index))

    def write_record(self, record: Mapping[str, object], *, idempotency_key: str) -> None:
        source_id = _assert_record(record)
        payload = _canonical(record)
        digest = hashlib.sha256(payload).hexdigest()
        previous = self._ledger.get(idempotency_key)
        if previous is not None:
            if previous != digest:
                raise SkillError(ErrorCode.IDEMPOTENCY_CONFLICT, "Idempotency key already has different content")
            self._ensure_lifecycle_event(idempotency_key, source_id, digest)
            return
        with _exclusive_source_lock(self._source_lock_target(source_id)):
            target = self._target(source_id, quarantined=record["lifecycle_state"] == "quarantined")
            alternate = self._target(source_id, quarantined=record["lifecycle_state"] != "quarantined")
            for existing_target in (target, alternate):
                if not existing_target.exists():
                    continue
                try:
                    existing_payload = existing_target.read_bytes()
                except OSError as exc:
                    raise SkillError(ErrorCode.STORAGE_CONFLICT, "Existing research record is unreadable") from exc
                if existing_target != target or existing_payload != payload:
                    raise SkillError(ErrorCode.STORAGE_CONFLICT, "Existing research record has different content")
            self._memory.write_record(record, idempotency_key=idempotency_key)
            if not target.exists():
                try:
                    _atomic_create(target, payload)
                except FileExistsError:
                    try:
                        winner = target.read_bytes()
                    except OSError as exc:
                        raise SkillError(ErrorCode.STORAGE_CONFLICT, "Racing research record is unreadable") from exc
                    if winner != payload:
                        raise SkillError(ErrorCode.STORAGE_CONFLICT, "Concurrent writer published different content")
            self._ensure_lifecycle_event(idempotency_key, source_id, digest)
            self._ledger[idempotency_key] = digest
            self._persist_ledger()

    def delete_record(self, source_id: str, *, reason: str) -> None:
        if not _SAFE_ID.fullmatch(source_id):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "source_id is not path-safe")
        media_targets: list[Path] = []
        for relative in (Path("downloads") / f"{source_id}.mp4", Path("downloads") / "receipts" / f"{source_id}.json"):
            target = self.root / relative
            parent = target.parent
            if not parent.exists():
                continue
            _assert_no_link_components(parent)
            if _is_link(parent) or _is_link(target) or target.parent.resolve() != parent.resolve():
                raise SkillError(ErrorCode.PATH_FORBIDDEN, "Research media path escaped its controlled root")
            media_targets.append(target)
        for quarantined in (False, True):
            target = self._target(source_id, quarantined=quarantined)
            if target.exists():
                target.unlink()
        for target in media_targets:
            if target.exists():
                target.unlink()
        self._memory.delete_record(source_id, reason=reason)
        audit_path = self.root / "audit" / "deletions.jsonl"
        self._assert_audit_path(audit_path)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"source_id": source_id, "reason": reason}, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
