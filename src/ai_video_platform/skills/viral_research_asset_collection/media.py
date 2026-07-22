"""Authorized, direct-public media download path for FTG-P-RESEARCH-002."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable, Mapping, Protocol
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .errors import ErrorCode, SkillError


MEDIA_DOWNLOAD_AUTHORIZATION_ID = "FTG-P-RESEARCH-002"
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_ATTEMPTS = 5
ALLOWED_HOST_SUFFIXES = (".tiktokcdn.com", ".tiktokcdn-eu.com", ".tiktokcdn-us.com")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class MediaResponse(Protocol):
    status: int
    headers: Mapping[str, str]
    def read(self, size: int = -1) -> bytes: ...
    def close(self) -> None: ...


class MediaTransport(Protocol):
    def get(self, url: str, *, timeout_seconds: int) -> MediaResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class UrllibMediaTransport:
    def __init__(self, *, authorization_id: str | None = None) -> None:
        if authorization_id != MEDIA_DOWNLOAD_AUTHORIZATION_ID:
            raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Media transport authorization is invalid")
        self._opener = build_opener(_NoRedirect())

    def get(self, url: str, *, timeout_seconds: int) -> MediaResponse:
        safe_url = _media_url({"media_url": url})
        return self._opener.open(
            Request(safe_url, method="GET", headers={"Accept": "video/*"}), timeout=timeout_seconds,
        )


def _atomic_write(path: Path, payload: bytes) -> None:
    fd, temp = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try: os.unlink(temp)
        except FileNotFoundError: pass


def _media_url(candidate: Mapping[str, object]) -> str:
    value = candidate.get("media_url")
    if not isinstance(value, str):
        video = candidate.get("video")
        value = video.get("url") if isinstance(video, Mapping) else None
    if not isinstance(value, str) or not value.strip():
        raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Candidate has no recorded public media URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Media URL is not a public HTTPS URL")
    host = (parsed.hostname or "").lower()
    if not host.endswith(ALLOWED_HOST_SUFFIXES):
        raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Media URL host is outside the authorized public CDN set")
    return value


@dataclass
class DirectMediaDownloadAdapter:
    root: Path
    authorization_id: str | None = None
    transport: MediaTransport | None = None
    now: Callable[[], datetime] | None = None

    def __post_init__(self) -> None:
        if self.authorization_id != MEDIA_DOWNLOAD_AUTHORIZATION_ID:
            raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Media download authorization is invalid")
        self.root = Path(os.path.abspath(os.fspath(self.root)))
        self.download_root = self.root / "downloads"
        self.receipt_root = self.download_root / "receipts"
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.transport = self.transport or UrllibMediaTransport(authorization_id=self.authorization_id)
        self.now = self.now or (lambda: datetime.now(timezone.utc))
        self.attempt_count = 0
        self.success_count = 0
        self.receipts: list[dict[str, object]] = []
        self.total_bytes = sum(p.stat().st_size for p in self.download_root.glob("*.mp4") if p.is_file())

    def _assert_ledgered_candidate(self, candidate: Mapping[str, object]) -> tuple[str, str, str]:
        source_id = candidate.get("source_id")
        digest = candidate.get("content_digest")
        if not isinstance(source_id, str) or not _SAFE_ID.fullmatch(source_id):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Candidate source identity is not path-safe")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Candidate digest is invalid")
        target = self.root / "metadata" / f"{source_id}.json"
        try:
            ledgered = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Candidate is not ledgered in the Research Library") from exc
        if not isinstance(ledgered, Mapping) or ledgered.get("content_digest") != digest:
            raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Candidate does not match its Research Library ledger")
        if ledgered.get("rights_status") != "UNKNOWN" or candidate.get("rights_status") != "UNKNOWN":
            raise SkillError(ErrorCode.RIGHTS_FORBIDDEN, "Media download must preserve UNKNOWN rights")
        media_url = _media_url(candidate)
        ledgered_video = ledgered.get("video")
        ledger_has_media_url = "media_url" in ledgered or (
            isinstance(ledgered_video, Mapping) and "url" in ledgered_video
        )
        if (
            (ledger_has_media_url and _media_url(ledgered) != media_url)
            or ledgered.get("source_url") != candidate.get("source_url")
            or ledgered.get("expires_at") != candidate.get("expires_at")
        ):
            raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Candidate media fields do not match its Research Library ledger")
        return source_id, digest, media_url

    def _write_failure_receipt(
        self, *, receipt_path: Path, digest: str, url: str, status: int | None,
        byte_count: int, content_digest: str, reason: str,
    ) -> None:
        receipt = {
            "candidate_digest": digest, "source_url": url, "http_status": status,
            "bytes": byte_count, "sha256": content_digest,
            "fetched_at": self.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "storage_path": None, "attempts": self.attempt_count,
            "lifecycle_state": "internal_analysis_only", "rights_status": "UNKNOWN",
            "outcome": "failed", "failure_reason": reason,
        }
        _atomic_write(receipt_path, json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        self.receipts.append(receipt)

    def recorded_failure_for(self, candidate: Mapping[str, object]) -> bool:
        return bool(
            self.receipts
            and self.receipts[-1].get("outcome") == "failed"
            and self.receipts[-1].get("candidate_digest") == candidate.get("content_digest")
        )

    def download(self, candidate: Mapping[str, object]) -> dict[str, object]:
        source_id, digest, url = self._assert_ledgered_candidate(candidate)
        path = self.download_root / f"{source_id}.mp4"
        receipt_path = self.receipt_root / f"{source_id}.json"
        expires = candidate.get("expires_at")
        if not isinstance(expires, str):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Candidate expiry is required")
        try:
            expiry = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            expired = expiry <= self.now()
            if expired and self.attempt_count >= MAX_ATTEMPTS:
                raise SkillError(ErrorCode.BUDGET_EXCEEDED, "Media download attempt budget exhausted")
            if expired:
                self.attempt_count += 1
            if expired and not path.exists() and not receipt_path.exists():
                self._write_failure_receipt(
                    receipt_path=receipt_path, digest=digest, url=url, status=None,
                    byte_count=0, content_digest=hashlib.sha256(b"").hexdigest(),
                    reason="candidate_expired",
                )
            if expired:
                raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Candidate media URL has expired")
        except ValueError as exc:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Candidate expiry is invalid") from exc
        if path.exists() != receipt_path.exists():
            raise SkillError(ErrorCode.STORAGE_CONFLICT, "Media asset and receipt must exist together")
        if path.exists() and receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SkillError(ErrorCode.STORAGE_CONFLICT, "Existing media receipt is unreadable") from exc
            if (
                not isinstance(receipt, dict)
                or receipt.get("candidate_digest") != digest
                or receipt.get("source_url") != url
                or receipt.get("storage_path") != str(path)
                or receipt.get("outcome") == "failed"
            ):
                raise SkillError(ErrorCode.STORAGE_CONFLICT, "Existing media receipt does not match the candidate")
            expected_bytes = receipt.get("bytes")
            expected_digest = receipt.get("sha256")
            if (
                not isinstance(expected_bytes, int)
                or isinstance(expected_bytes, bool)
                or not isinstance(expected_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
            ):
                raise SkillError(ErrorCode.STORAGE_CONFLICT, "Existing media receipt has invalid integrity fields")
            existing_hasher = hashlib.sha256()
            try:
                if path.stat().st_size != expected_bytes:
                    raise SkillError(ErrorCode.STORAGE_CONFLICT, "Existing media asset size does not match its receipt")
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        existing_hasher.update(chunk)
            except SkillError:
                raise
            except OSError as exc:
                raise SkillError(ErrorCode.STORAGE_CONFLICT, "Existing media asset is unreadable") from exc
            if existing_hasher.hexdigest() != expected_digest:
                raise SkillError(ErrorCode.STORAGE_CONFLICT, "Existing media asset digest does not match its receipt")
            self.receipts.append(receipt)
            return receipt
        if self.success_count >= 3:
            raise SkillError(ErrorCode.BUDGET_EXCEEDED, "Media download success budget exhausted")
        if self.attempt_count >= MAX_ATTEMPTS:
            raise SkillError(ErrorCode.BUDGET_EXCEEDED, "Media download attempt budget exhausted")
        self.attempt_count += 1
        response = None
        temp_path: Path | None = None
        status: int | None = None
        total = 0
        hasher = hashlib.sha256()
        try:
            response = self.transport.get(url, timeout_seconds=120)
            status = int(response.status)
            if status != 200:
                raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Media GET did not return HTTP 200")
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if not content_type.startswith("video/"):
                raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Media response is not a video")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_FILE_BYTES:
                raise SkillError(ErrorCode.BUDGET_EXCEEDED, "Media file exceeds per-file byte cap")
            fd, temp = tempfile.mkstemp(prefix=f".{source_id}-", suffix=".part", dir=self.download_root)
            temp_path = Path(temp)
            with os.fdopen(fd, "wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk: break
                    total += len(chunk)
                    if total > MAX_FILE_BYTES or self.total_bytes + total > MAX_TOTAL_BYTES:
                        raise SkillError(ErrorCode.BUDGET_EXCEEDED, "Media byte budget exceeded")
                    handle.write(chunk); hasher.update(chunk)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temp_path, path); temp_path = None
            fetched_at = self.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            receipt = {
                "candidate_digest": digest, "source_url": url, "http_status": status,
                "bytes": total, "sha256": hasher.hexdigest(), "fetched_at": fetched_at,
                "storage_path": str(path), "attempts": self.attempt_count,
                "lifecycle_state": "internal_analysis_only", "rights_status": "UNKNOWN",
            }
            try:
                _atomic_write(receipt_path, json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            except OSError:
                try:
                    path.unlink()
                except OSError:
                    pass
                raise
            self.total_bytes += total
            self.success_count += 1
            self.receipts.append(receipt)
            return receipt
        except SkillError as exc:
            self._write_failure_receipt(
                receipt_path=receipt_path, digest=digest, url=url, status=status,
                byte_count=total, content_digest=hasher.hexdigest(), reason=exc.code.value,
            )
            raise
        except (OSError, ValueError) as exc:
            status = getattr(exc, "code", status)
            self._write_failure_receipt(
                receipt_path=receipt_path, digest=digest, url=url,
                status=int(status) if isinstance(status, int) else None,
                byte_count=total, content_digest=hasher.hexdigest(),
                reason=ErrorCode.DOWNLOAD_FORBIDDEN.value,
            )
            raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Media download failed") from exc
        finally:
            if response is not None: response.close()
            if temp_path is not None:
                try: temp_path.unlink()
                except FileNotFoundError: pass
