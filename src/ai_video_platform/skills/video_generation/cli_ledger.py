"""Persistent task-workspace evidence for the explicit Seedance.nz owner CLI."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from .errors import GenerationError, GenerationErrorCode, contains_sensitive_text
from .models import canonical_json, snapshot


ARTIFACT_NAME = "seedance_nz_video.mp4"
RECEIPT_NAME = "seedance_nz_video_receipt.json"
LOCK_NAME = ".seedance_nz_execution.lock"


def resolve_output_directory(input_path: Path, output_dir: Path) -> Path:
    request_path = input_path.resolve(strict=True)
    if not request_path.is_file():
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Seedance.nz input must be a request file")
    workspace = request_path.parent
    resolved = output_dir.resolve(strict=False)
    if resolved == workspace or not resolved.is_relative_to(workspace):
        raise GenerationError(
            GenerationErrorCode.INVALID_INPUT,
            "Seedance.nz output directory must be inside the request task workspace",
            field_paths=("output_dir",),
        )
    if resolved.exists() and not resolved.is_dir():
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Seedance.nz output path must be a directory")
    return resolved


class SeedanceNzCliLedger:
    """Exclusive, replay-aware persistence without cross-process in-memory state."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.artifact_path = output_dir / ARTIFACT_NAME
        self.receipt_path = output_dir / RECEIPT_NAME
        self.lock_path = output_dir / LOCK_NAME
        self._lock_fd: int | None = None

    def replay(self, *, idempotency_key: str, request_hash: str) -> dict[str, object] | None:
        artifact_exists = self.artifact_path.exists()
        receipt_exists = self.receipt_path.exists()
        if not artifact_exists and not receipt_exists:
            return None
        if artifact_exists != receipt_exists or not self.artifact_path.is_file() or not self.receipt_path.is_file():
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Seedance.nz evidence set is incomplete")
        try:
            raw = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Seedance.nz receipt is invalid") from None
        if not isinstance(raw, Mapping):
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Seedance.nz receipt is invalid")
        receipt = snapshot(raw)
        supplied_receipt_digest = receipt.pop("receipt_digest", None)
        calculated_receipt_digest = "sha256:" + hashlib.sha256(canonical_json(receipt).encode("utf-8")).hexdigest()
        if receipt.get("idempotency_key") != idempotency_key:
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Seedance.nz output belongs to another request")
        if receipt.get("request_hash") != request_hash:
            raise GenerationError(
                GenerationErrorCode.IDEMPOTENCY_MISMATCH,
                "Idempotency key was already used for a different Seedance.nz request",
            )
        content = self.artifact_path.read_bytes()
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if (
            not content
            or receipt.get("artifact_file") != ARTIFACT_NAME
            or receipt.get("receipt_file") != RECEIPT_NAME
            or receipt.get("release_status") != "CONTROLLED_FIRST_RUN_REQUIRED"
            or receipt.get("state") != "downloaded"
            or receipt.get("content_type") != "video/mp4"
            or receipt.get("byte_size") != len(content)
            or receipt.get("sha256") != actual
            or supplied_receipt_digest != calculated_receipt_digest
            or not isinstance(receipt.get("job_id"), str)
            or not isinstance(receipt.get("provider_job_id"), str)
            or contains_sensitive_text(canonical_json(receipt))
        ):
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Seedance.nz receipt or artifact was modified")
        receipt["receipt_digest"] = supplied_receipt_digest
        receipt["replayed"] = True
        return receipt

    def acquire(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise GenerationError(
                GenerationErrorCode.CONCURRENCY_LIMIT,
                "Another Seedance.nz execution owns this task workspace output",
            ) from None
        if self.artifact_path.exists() or self.receipt_path.exists():
            self.release()
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Seedance.nz evidence already exists")

    def persist(self, content: bytes, receipt: Mapping[str, object]) -> None:
        if self._lock_fd is None:
            raise GenerationError(GenerationErrorCode.INVALID_TRANSITION, "Seedance.nz output is not reserved")
        artifact_temp = self.output_dir / (ARTIFACT_NAME + ".tmp")
        receipt_temp = self.output_dir / (RECEIPT_NAME + ".tmp")
        if artifact_temp.exists() or receipt_temp.exists():
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Seedance.nz temporary evidence already exists")
        try:
            with artifact_temp.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            with receipt_temp.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical_json(receipt) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            if self.artifact_path.exists() or self.receipt_path.exists():
                raise GenerationError(GenerationErrorCode.IDEMPOTENCY_MISMATCH, "Seedance.nz evidence already exists")
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
