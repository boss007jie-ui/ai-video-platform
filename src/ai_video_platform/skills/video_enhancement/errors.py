"""Stable, redacted errors for Video Enhancement."""

from __future__ import annotations

from enum import Enum
import re
from typing import Any, Mapping


class EnhancementErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    INPUT_FILE_INVALID = "INPUT_FILE_INVALID"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    INPUT_DIGEST_MISMATCH = "INPUT_DIGEST_MISMATCH"
    RIGHTS_REJECTED = "RIGHTS_REJECTED"
    WORKFLOW_PROFILE_INVALID = "WORKFLOW_PROFILE_INVALID"
    OPERATION_UNSUPPORTED = "OPERATION_UNSUPPORTED"
    BUDGET_INVALID = "BUDGET_INVALID"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    IDEMPOTENCY_REQUIRED = "IDEMPOTENCY_REQUIRED"
    NETWORK_BLOCKED = "NETWORK_BLOCKED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_RETRY_EXHAUSTED = "PROVIDER_RETRY_EXHAUSTED"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    IDEMPOTENCY_MISMATCH = "IDEMPOTENCY_MISMATCH"
    REQUEST_LIMIT = "REQUEST_LIMIT"
    CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"
    DOWNLOAD_INTEGRITY_FAILED = "DOWNLOAD_INTEGRITY_FAILED"


_SENSITIVE_KEY = re.compile(r"(?i)(authorization|credential|api[_-]?key|token|secret|password|private[_-]?key|traceback|stack)")
_SENSITIVE_VALUE = re.compile(
    r"(?:\bBearer\s+[A-Za-z0-9._~+/=-]{12,}|\bsk-[A-Za-z0-9_-]{20,}\b|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"(?:[?&](?:token|key|signature|sig|credential|auth)=)[^&\s]+)",
    re.IGNORECASE,
)


def contains_sensitive_text(value: str) -> bool:
    return _SENSITIVE_VALUE.search(value) is not None


def sanitize_sensitive(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key) and key not in {"authorization_id"}:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(name): sanitize_sensitive(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_sensitive(item) for item in value]
    if isinstance(value, str) and contains_sensitive_text(value):
        return "[REDACTED]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


class EnhancementError(ValueError):
    def __init__(
        self,
        code: EnhancementErrorCode,
        message: str,
        *,
        field_paths: tuple[str, ...] = (),
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        safe = sanitize_sensitive(message)
        self.message = safe if isinstance(safe, str) else "Rejected unsafe input"
        super().__init__(self.message)
        self.field_paths = tuple(str(sanitize_sensitive(path)) for path in field_paths)
        self.details = sanitize_sensitive(details or {})
        self.retryable = retryable

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "category": "validation",
            "retryable": self.retryable,
            "message": self.message,
            "field_paths": list(self.field_paths),
            "details": self.details,
        }
