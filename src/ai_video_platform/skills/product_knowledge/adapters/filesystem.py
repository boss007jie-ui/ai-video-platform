"""Atomic, local-filesystem Product Library adapter."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterator

from ai_video_platform.contracts.serialization import canonical_json, content_digest, parse_json_object
from ai_video_platform.core.guards import LegacyPathGuard
from ai_video_platform.core.ids import uuid7

from ..errors import ProductKnowledgeError, ProductKnowledgeErrorCode
from .authority import require_product_knowledge_writer
from .memory import empty_library_state


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class FilesystemProductLibrary:
    """Production/local adapter backed by one atomically replaced metadata file."""

    _DIRECTORIES = (
        "metadata",
        "objects/sha256",
        "manifests/assets",
        "manifests/sources",
        "exports/confirmed",
        "exports/review",
        "events/feedback",
        "events/approvals",
        "audit/entries",
        "snapshots",
        "quarantine",
        "locks",
    )

    def __init__(self, root: Path | str, *, lock_timeout_seconds: float = 5.0) -> None:
        guard = LegacyPathGuard()
        candidate = guard.assert_allowed(Path(root)).resolve()
        guard.assert_allowed(candidate)
        self.root = candidate
        self.lock_timeout_seconds = lock_timeout_seconds
        for relative in self._DIRECTORIES:
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self._state_path = self.root / "metadata" / "library.json"
        self._lock_path = self.root / "locks" / "writer.lock"
        if not self._state_path.exists():
            self._write_state_atomic(empty_library_state())

    @contextmanager
    def _writer_lock(self) -> Iterator[None]:
        deadline = time.monotonic() + self.lock_timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(descriptor, str(os.getpid()).encode("ascii"))
            except FileExistsError as exc:
                if time.monotonic() >= deadline:
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.PRODUCT_LIBRARY_LOCK_TIMEOUT,
                        "Timed out waiting for the Product Library writer lock",
                        retryable=True,
                    ) from exc
                time.sleep(0.01)
        try:
            yield
        finally:
            os.close(descriptor)
            try:
                self._lock_path.unlink()
            except FileNotFoundError:
                pass

    def _read_state(self) -> dict[str, Any]:
        return parse_json_object(self._state_path.read_bytes(), max_bytes=32 * 1024 * 1024)

    def _write_state_atomic(self, state: dict[str, Any]) -> None:
        temporary = self._state_path.with_name(f".{self._state_path.name}.{uuid7()}.tmp")
        payload = canonical_json(state).encode("utf-8")
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._state_path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._read_state())

    def _mirror_audit_best_effort(self, entry: dict[str, Any]) -> None:
        try:
            target = self.root / "audit" / "entries" / f"{entry['after_revision']:012d}.json"
            target.write_text(canonical_json(entry), encoding="utf-8")
        except OSError:
            pass

    def commit(
        self,
        *,
        writer_authority: object,
        command: str,
        idempotency_key: str,
        input_digest: str,
        actor: str,
        reason: str,
        expected_revision: int,
        update: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        require_product_knowledge_writer(writer_authority)
        with self._writer_lock():
            state = self._read_state()
            replay = state["idempotency"].get(idempotency_key)
            if replay is not None:
                if replay.get("restored_out_at_revision") is not None:
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.IDEMPOTENCY_RESTORED_OUT,
                        "Command result was rolled back by a verified snapshot restore",
                        details={"restored_out_at_revision": replay["restored_out_at_revision"]},
                    )
                if replay["command"] != command or replay["input_digest"] != input_digest:
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.IDEMPOTENCY_MISMATCH,
                        "Idempotency key was already used for a different command input",
                    )
                return deepcopy(replay["result"])
            if state["revision"] != expected_revision:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.LIBRARY_VERSION_CONFLICT,
                    "Product Library revision changed",
                    retryable=True,
                    details={"expected_revision": expected_revision, "actual_revision": state["revision"]},
                )
            next_state = deepcopy(state)
            result = update(next_state)
            before_revision = state["revision"]
            next_state["revision"] = before_revision + 1
            next_state["idempotency"][idempotency_key] = {
                "command": command,
                "input_digest": input_digest,
                "result": deepcopy(result),
            }
            audit_entry = {
                "audit_id": f"audit-{next_state['revision']:012d}",
                "writer_id": "product-knowledge",
                "command": command,
                "actor": actor,
                "reason": reason,
                "idempotency_key": idempotency_key,
                "input_digest": input_digest,
                "before_revision": before_revision,
                "after_revision": next_state["revision"],
                "occurred_at": _utc_now(),
            }
            next_state["audit"].append(audit_entry)
            self._write_state_atomic(next_state)
        self._mirror_audit_best_effort(audit_entry)
        return deepcopy(result)

    def backup(self, *, writer_authority: object, actor: str, reason: str) -> Path:
        require_product_knowledge_writer(writer_authority)
        with self._writer_lock():
            state = self._read_state()
            snapshot_id = f"snapshot-{state['revision']:012d}-{uuid7()}"
            temporary = self.root / "snapshots" / f".{snapshot_id}.tmp"
            target = self.root / "snapshots" / snapshot_id
            temporary.mkdir()
            try:
                (temporary / "library.json").write_text(canonical_json(state), encoding="utf-8")
                manifest = {
                    "snapshot_id": snapshot_id,
                    "schema_version": state["schema_version"],
                    "source_revision": state["revision"],
                    "state_digest": content_digest(state),
                    "created_at": _utc_now(),
                    "actor": actor,
                    "reason": reason,
                }
                (temporary / "manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    for child in temporary.iterdir():
                        child.unlink()
                    temporary.rmdir()
        return target

    def restore(
        self,
        snapshot_path: Path | str,
        *,
        writer_authority: object,
        expected_revision: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        require_product_knowledge_writer(writer_authority)
        candidate = Path(snapshot_path).resolve()
        snapshots_root = (self.root / "snapshots").resolve()
        if os.path.commonpath((str(candidate), str(snapshots_root))) != str(snapshots_root):
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.PRODUCT_LIBRARY_PATH_FORBIDDEN,
                "Restore snapshot must be inside the Product Library snapshot root",
            )
        snapshot_state = parse_json_object((candidate / "library.json").read_bytes(), max_bytes=32 * 1024 * 1024)
        manifest = parse_json_object((candidate / "manifest.json").read_bytes())
        if manifest.get("state_digest") != content_digest(snapshot_state):
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.BACKUP_INTEGRITY_FAILED,
                "Snapshot digest verification failed",
            )
        with self._writer_lock():
            current = self._read_state()
            if current["revision"] != expected_revision:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.LIBRARY_VERSION_CONFLICT,
                    "Product Library revision changed",
                    retryable=True,
                    details={"expected_revision": expected_revision, "actual_revision": current["revision"]},
                )
            restored = deepcopy(snapshot_state)
            restored["audit"] = deepcopy(current["audit"])
            restored["revision"] = current["revision"] + 1
            restored_idempotency = deepcopy(snapshot_state["idempotency"])
            for key, record in current["idempotency"].items():
                if key in restored_idempotency:
                    continue
                restored_out = deepcopy(record)
                restored_out["restored_out_at_revision"] = restored["revision"]
                restored_idempotency[key] = restored_out
            restored["idempotency"] = restored_idempotency
            audit_entry = {
                "audit_id": f"audit-{restored['revision']:012d}",
                "writer_id": "product-knowledge",
                "command": "restore-snapshot",
                "actor": actor,
                "reason": reason,
                "idempotency_key": f"restore:{manifest['snapshot_id']}:{expected_revision}",
                "input_digest": manifest["state_digest"],
                "before_revision": current["revision"],
                "after_revision": restored["revision"],
                "occurred_at": _utc_now(),
            }
            restored["audit"].append(audit_entry)
            self._write_state_atomic(restored)
        self._mirror_audit_best_effort(audit_entry)
        return {"snapshot_id": manifest["snapshot_id"], "revision": restored["revision"]}
