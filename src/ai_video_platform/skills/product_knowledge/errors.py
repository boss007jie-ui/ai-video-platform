"""Stable, sanitized errors owned by Product Knowledge."""

from __future__ import annotations

from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping


_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|api[_-]?key|token|secret|password|credential|private[_-]?key|traceback|stack)"
)


def _sanitize(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return MappingProxyType({str(name): _sanitize(item, key=str(name)) for name, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_sanitize(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


def _to_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {name: _to_json(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_to_json(item) for item in value]
    return value


class ProductKnowledgeErrorCode(str, Enum):
    PRODUCT_MATCH_AMBIGUOUS = "PRODUCT_MATCH_AMBIGUOUS"
    FEEDBACK_NOT_FOUND = "FEEDBACK_NOT_FOUND"
    FEEDBACK_NOT_CONFIRMED = "FEEDBACK_NOT_CONFIRMED"
    REVIEW_AUTHORITY_INSUFFICIENT = "REVIEW_AUTHORITY_INSUFFICIENT"
    APPROVAL_SUBJECT_MISMATCH = "APPROVAL_SUBJECT_MISMATCH"
    IDEMPOTENCY_MISMATCH = "IDEMPOTENCY_MISMATCH"
    LIBRARY_VERSION_CONFLICT = "LIBRARY_VERSION_CONFLICT"
    PRODUCT_LIBRARY_WRITE_FORBIDDEN = "PRODUCT_LIBRARY_WRITE_FORBIDDEN"
    PRODUCT_LIBRARY_LOCK_TIMEOUT = "PRODUCT_LIBRARY_LOCK_TIMEOUT"
    BACKUP_INTEGRITY_FAILED = "BACKUP_INTEGRITY_FAILED"
    PRODUCT_LIBRARY_PATH_FORBIDDEN = "PRODUCT_LIBRARY_PATH_FORBIDDEN"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    SKU_NOT_FOUND = "SKU_NOT_FOUND"
    AGGREGATE_VERSION_CONFLICT = "AGGREGATE_VERSION_CONFLICT"
    CONFLICT_NOT_FOUND = "CONFLICT_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    IDEMPOTENCY_RESTORED_OUT = "IDEMPOTENCY_RESTORED_OUT"
    FEEDBACK_EVENT_IMMUTABLE = "FEEDBACK_EVENT_IMMUTABLE"


class ProductKnowledgeError(Exception):
    def __init__(
        self,
        code: ProductKnowledgeErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = _sanitize(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "details": _to_json(self.details),
        }
