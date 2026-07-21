"""Owner-local atomic state stores for versioning and exact replay."""

from __future__ import annotations

import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Literal, Mapping, Protocol

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - exercised by the target platform's equivalent lock path
    import fcntl

from ai_video_platform.contracts.errors import ContractError
from ai_video_platform.contracts.serialization import (
    canonical_json,
    content_digest,
    freeze_json,
    parse_json_object,
    thaw_json,
)
from ai_video_platform.core.guards import LegacyPathGuard


CommitOutcome = Literal["recorded", "replay", "idempotency-conflict", "stale"]
MAX_STATE_BYTES = 8 * 1_048_576


class VersionStoreError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class VersionStore(Protocol):
    def current(self, task_id: str, product_id: str) -> int | None: ...

    def lookup(self, idempotency_key: str) -> Mapping[str, object] | None: ...

    def record_outcome(
        self,
        idempotency_key: str,
        request_digest: str,
        result: Mapping[str, object],
    ) -> CommitOutcome: ...

    def commit(
        self,
        task_id: str,
        product_id: str,
        *,
        expected: int | None,
        new_version: int,
        idempotency_key: str,
        request_digest: str,
        result: Mapping[str, object],
    ) -> CommitOutcome: ...


class InMemoryVersionStore:
    def __init__(self) -> None:
        self._versions: dict[str, int] = {}
        self._records: dict[str, Mapping[str, object]] = {}
        self._lock = Lock()

    @staticmethod
    def _version_key(task_id: str, product_id: str) -> str:
        return content_digest({"task_id": task_id, "product_id": product_id})

    @staticmethod
    def _record_key(idempotency_key: str) -> str:
        return content_digest({"idempotency_key": idempotency_key})

    def current(self, task_id: str, product_id: str) -> int | None:
        with self._lock:
            return self._versions.get(self._version_key(task_id, product_id))

    def lookup(self, idempotency_key: str) -> Mapping[str, object] | None:
        with self._lock:
            return self._records.get(self._record_key(idempotency_key))

    def record_outcome(
        self,
        idempotency_key: str,
        request_digest: str,
        result: Mapping[str, object],
    ) -> CommitOutcome:
        with self._lock:
            return self._record_locked(idempotency_key, request_digest, result)

    def commit(
        self,
        task_id: str,
        product_id: str,
        *,
        expected: int | None,
        new_version: int,
        idempotency_key: str,
        request_digest: str,
        result: Mapping[str, object],
    ) -> CommitOutcome:
        with self._lock:
            replay = self._existing_outcome(idempotency_key, request_digest)
            if replay is not None:
                return replay
            key = self._version_key(task_id, product_id)
            if self._versions.get(key) != expected:
                return "stale"
            self._versions[key] = new_version
            return self._record_locked(idempotency_key, request_digest, result)

    def _existing_outcome(self, idempotency_key: str, request_digest: str) -> CommitOutcome | None:
        existing = self._records.get(self._record_key(idempotency_key))
        if existing is None:
            return None
        return "replay" if existing["request_digest"] == request_digest else "idempotency-conflict"

    def _record_locked(
        self,
        idempotency_key: str,
        request_digest: str,
        result: Mapping[str, object],
    ) -> CommitOutcome:
        existing = self._existing_outcome(idempotency_key, request_digest)
        if existing is not None:
            return existing
        self._records[self._record_key(idempotency_key)] = freeze_json(
            {"request_digest": request_digest, "result": result}
        )
        return "recorded"


class FileVersionStore:
    """Atomic JSON state at a resolved path contained by an explicit Task Workspace."""

    def __init__(
        self,
        path: Path | str,
        *,
        workspace_root: Path | str,
        lock_timeout_seconds: float = 1.0,
    ) -> None:
        try:
            root = Path(workspace_root).resolve(strict=True)
            resolved = Path(path).resolve(strict=False)
            guard = LegacyPathGuard()
            self.workspace_root = guard.assert_allowed(root)
            self.path = guard.assert_allowed(resolved)
        except (OSError, RuntimeError, ContractError) as exc:
            raise VersionStoreError(
                "STORYBOARD_STATE_PATH_FORBIDDEN",
                "Storyboard state path is unavailable or forbidden",
            ) from exc
        if not self.workspace_root.is_dir():
            raise VersionStoreError(
                "STORYBOARD_STATE_PATH_FORBIDDEN",
                "Storyboard Task Workspace must be an existing directory",
            )
        try:
            relative = self.path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise VersionStoreError(
                "STORYBOARD_STATE_PATH_FORBIDDEN",
                "Storyboard state path must remain inside the Task Workspace",
            ) from exc
        if not relative.parts:
            raise VersionStoreError(
                "STORYBOARD_STATE_PATH_FORBIDDEN",
                "Storyboard state path must name a file inside the Task Workspace",
            )
        self.lock_path = Path(f"{self.path}.lock")
        self.lock_timeout_seconds = lock_timeout_seconds

    @staticmethod
    def _version_key(task_id: str, product_id: str) -> str:
        return content_digest({"task_id": task_id, "product_id": product_id})

    @staticmethod
    def _record_key(idempotency_key: str) -> str:
        return content_digest({"idempotency_key": idempotency_key})

    def current(self, task_id: str, product_id: str) -> int | None:
        data = self._read()
        value = data["versions"].get(self._version_key(task_id, product_id))
        return int(value) if value is not None else None

    def lookup(self, idempotency_key: str) -> Mapping[str, object] | None:
        data = self._read()
        record = data["records"].get(self._record_key(idempotency_key))
        return freeze_json(record) if record is not None else None

    def record_outcome(
        self,
        idempotency_key: str,
        request_digest: str,
        result: Mapping[str, object],
    ) -> CommitOutcome:
        descriptor = self._acquire_lock()
        try:
            data = self._read()
            existing = self._existing_outcome(data, idempotency_key, request_digest)
            if existing is not None:
                return existing
            data["records"][self._record_key(idempotency_key)] = {
                "request_digest": request_digest,
                "result": thaw_json(freeze_json(result)),
            }
            self._write(data)
            return "recorded"
        finally:
            self._release_lock(descriptor)

    def commit(
        self,
        task_id: str,
        product_id: str,
        *,
        expected: int | None,
        new_version: int,
        idempotency_key: str,
        request_digest: str,
        result: Mapping[str, object],
    ) -> CommitOutcome:
        descriptor = self._acquire_lock()
        try:
            data = self._read()
            existing = self._existing_outcome(data, idempotency_key, request_digest)
            if existing is not None:
                return existing
            key = self._version_key(task_id, product_id)
            if data["versions"].get(key) != expected:
                return "stale"
            data["versions"][key] = new_version
            data["records"][self._record_key(idempotency_key)] = {
                "request_digest": request_digest,
                "result": thaw_json(freeze_json(result)),
            }
            self._write(data)
            return "recorded"
        finally:
            self._release_lock(descriptor)

    def _existing_outcome(
        self,
        data: dict,
        idempotency_key: str,
        request_digest: str,
    ) -> CommitOutcome | None:
        record = data["records"].get(self._record_key(idempotency_key))
        if record is None:
            return None
        return "replay" if record["request_digest"] == request_digest else "idempotency-conflict"

    def _read(self) -> dict:
        if not self.path.exists():
            return {"schema_version": "1.0.0", "versions": {}, "records": {}}
        try:
            with self.path.open("rb") as handle:
                document = parse_json_object(
                    handle.read(MAX_STATE_BYTES + 1),
                    max_bytes=MAX_STATE_BYTES,
                )
        except (OSError, ContractError) as exc:
            raise VersionStoreError(
                "STORYBOARD_STATE_CORRUPTED",
                "Storyboard state is unreadable or malformed",
            ) from exc
        if (
            document.get("schema_version") != "1.0.0"
            or not isinstance(document.get("versions"), dict)
            or not isinstance(document.get("records"), dict)
        ):
            raise VersionStoreError(
                "STORYBOARD_STATE_CORRUPTED",
                "Storyboard state uses an unsupported structure",
            )
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in document["versions"].values()):
            raise VersionStoreError(
                "STORYBOARD_STATE_CORRUPTED",
                "Storyboard state contains an invalid version",
            )
        for record in document["records"].values():
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("request_digest"), str)
                or not isinstance(record.get("result"), dict)
            ):
                raise VersionStoreError(
                    "STORYBOARD_STATE_CORRUPTED",
                    "Storyboard state contains an invalid replay record",
                )
        return document

    def _write(self, document: dict) -> None:
        if not self.path.parent.is_dir():
            raise VersionStoreError(
                "STORYBOARD_STATE_UNAVAILABLE",
                "Storyboard state parent directory does not exist",
            )
        temporary_name: str | None = None
        try:
            serialized = canonical_json(document)
            if len(serialized.encode("utf-8")) > MAX_STATE_BYTES:
                raise VersionStoreError(
                    "STORYBOARD_STATE_BUDGET_EXCEEDED",
                    "Storyboard state exceeds the 8 MiB owner-local budget",
                )
            with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary_name = handle.name
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        except OSError as exc:
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink()
                except FileNotFoundError:
                    pass
            raise VersionStoreError(
                "STORYBOARD_STATE_UNAVAILABLE",
                "Storyboard state could not be committed",
                retryable=True,
            ) from exc

    def _acquire_lock(self) -> int:
        descriptor: int | None = None
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise VersionStoreError(
                "STORYBOARD_STATE_UNAVAILABLE",
                "Storyboard state lock could not be opened",
                retryable=True,
            ) from exc
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - target platform is Windows
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return descriptor
            except OSError as exc:
                if time.monotonic() >= deadline:
                    os.close(descriptor)
                    raise VersionStoreError(
                        "STORYBOARD_STATE_LOCK_TIMEOUT",
                        "Storyboard state is busy",
                        retryable=True,
                    ) from exc
                time.sleep(0.01)

    @staticmethod
    def _release_lock(descriptor: int) -> None:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - target platform is Windows
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
