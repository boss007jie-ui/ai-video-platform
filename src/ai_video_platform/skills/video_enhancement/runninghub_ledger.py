"""Persistent task-workspace evidence for explicit RunningHub enhancement."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from .errors import EnhancementError, EnhancementErrorCode, contains_sensitive_text
from .models import canonical_json, snapshot


ARTIFACT_NAME = "runninghub_enhanced.mp4"
RECEIPT_NAME = "runninghub_enhancement_receipt.json"
LOCK_NAME = ".runninghub_enhancement.lock"
PENDING_RECEIPT_FIELDS = frozenset({"task_id", "idempotency_key", "request_hash", "submitted_at"})


class RunningHubCliLedger:
    """Exclusive, replay-aware persistence colocated with task media."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.artifact_path = workspace / ARTIFACT_NAME
        self.receipt_path = workspace / RECEIPT_NAME
        self.lock_path = workspace / LOCK_NAME
        self._lock_fd: int | None = None

    def replay(self, *, idempotency_key: str, request_hash: str) -> dict[str, object] | None:
        artifact_exists = self.artifact_path.exists()
        receipt_exists = self.receipt_path.exists()
        if not artifact_exists and not receipt_exists:
            return None
        if artifact_exists != receipt_exists or not self.artifact_path.is_file() or not self.receipt_path.is_file():
            self._mismatch("RunningHub evidence set is incomplete")
        try:
            raw = json.loads(self.receipt_path.read_text(encoding="utf-8"))
            content = self.artifact_path.read_bytes()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._mismatch("RunningHub evidence is unreadable")
        if not isinstance(raw, Mapping):
            self._mismatch("RunningHub receipt is invalid")
        receipt = snapshot(raw)
        supplied_receipt_digest = receipt.pop("receipt_digest", None)
        calculated_receipt_digest = "sha256:" + hashlib.sha256(canonical_json(receipt).encode("utf-8")).hexdigest()
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if (
            receipt.get("idempotency_key") != idempotency_key
            or receipt.get("request_hash") != request_hash
            or receipt.get("state") != "downloaded"
            or receipt.get("artifact_file") != ARTIFACT_NAME
            or receipt.get("receipt_file") != RECEIPT_NAME
            or receipt.get("output_size_bytes") != len(content)
            or receipt.get("output_sha256") != actual
            or receipt.get("output_media_type") != "video/mp4"
            or supplied_receipt_digest != calculated_receipt_digest
            or contains_sensitive_text(canonical_json(receipt))
        ):
            self._mismatch("RunningHub receipt or artifact was modified")
        receipt["receipt_digest"] = supplied_receipt_digest
        receipt["replayed"] = True
        return receipt

    def acquire(self) -> None:
        if not self.workspace.is_dir():
            raise EnhancementError(EnhancementErrorCode.INPUT_FILE_INVALID, "RunningHub task workspace is invalid")
        try:
            self._lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise EnhancementError(
                EnhancementErrorCode.CONCURRENCY_LIMIT,
                "Another RunningHub enhancement owns this task workspace",
            ) from None
        if self.artifact_path.exists() or self.receipt_path.exists():
            self.release()
            self._mismatch("RunningHub evidence already exists")

    def persist_pending(self, receipt: Mapping[str, object]) -> None:
        if self._lock_fd is None:
            raise EnhancementError(EnhancementErrorCode.INVALID_TRANSITION, "RunningHub output is not reserved")
        value = snapshot(receipt)
        if (
            set(value) != PENDING_RECEIPT_FIELDS
            or any(not isinstance(value.get(field), str) or not value[field] for field in PENDING_RECEIPT_FIELDS)
            or contains_sensitive_text(canonical_json(value))
        ):
            self._mismatch("RunningHub pending receipt is invalid")
        if self.artifact_path.exists() or self.receipt_path.exists():
            self._mismatch("RunningHub evidence already exists")
        receipt_temp = self.workspace / (RECEIPT_NAME + ".tmp")
        if receipt_temp.exists():
            self._mismatch("RunningHub temporary evidence already exists")
        try:
            with receipt_temp.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical_json(value) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            receipt_temp.replace(self.receipt_path)
        finally:
            receipt_temp.unlink(missing_ok=True)

    def persist_before_download(self, receipt: Mapping[str, object]) -> None:
        if self._lock_fd is None or not self.receipt_path.is_file() or self.artifact_path.exists():
            self._mismatch("RunningHub pending receipt cannot be promoted")
        try:
            raw_pending = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._mismatch("RunningHub pending receipt is unreadable")
        if not isinstance(raw_pending, Mapping):
            self._mismatch("RunningHub pending receipt is invalid")
        pending = snapshot(raw_pending)
        value = snapshot(receipt)
        if (
            set(pending) != PENDING_RECEIPT_FIELDS
            or any(pending.get(field) != value.get(field) for field in PENDING_RECEIPT_FIELDS)
            or contains_sensitive_text(canonical_json(pending))
            or contains_sensitive_text(canonical_json(value))
        ):
            self._mismatch("RunningHub pending receipt identity does not match")
        receipt_temp = self.workspace / (RECEIPT_NAME + ".tmp")
        if receipt_temp.exists():
            self._mismatch("RunningHub temporary evidence already exists")
        try:
            with receipt_temp.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical_json(value) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            receipt_temp.replace(self.receipt_path)
        finally:
            receipt_temp.unlink(missing_ok=True)

    def finalize(self, content: bytes, receipt: Mapping[str, object]) -> None:
        if self._lock_fd is None or not self.receipt_path.is_file() or self.artifact_path.exists():
            self._mismatch("RunningHub evidence cannot be finalized")
        artifact_temp = self.workspace / (ARTIFACT_NAME + ".tmp")
        receipt_temp = self.workspace / (RECEIPT_NAME + ".tmp")
        if artifact_temp.exists() or receipt_temp.exists():
            self._mismatch("RunningHub temporary evidence already exists")
        try:
            with artifact_temp.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            with receipt_temp.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical_json(receipt) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            artifact_temp.replace(self.artifact_path)
            receipt_temp.replace(self.receipt_path)
        finally:
            artifact_temp.unlink(missing_ok=True)
            receipt_temp.unlink(missing_ok=True)

    def release(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        self.lock_path.unlink(missing_ok=True)

    @staticmethod
    def _mismatch(message: str) -> None:
        raise EnhancementError(EnhancementErrorCode.IDEMPOTENCY_MISMATCH, message)
