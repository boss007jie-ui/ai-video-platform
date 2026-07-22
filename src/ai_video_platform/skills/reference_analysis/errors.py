"""Stable, recursively redacted Reference Analysis errors."""

from __future__ import annotations

from enum import Enum
import re
from typing import Any, Mapping


class ErrorCode(str, Enum):
    VALIDATION_FAILED = "REFERENCE_ANALYSIS_VALIDATION_FAILED"
    SCOPE_FORBIDDEN = "REFERENCE_ANALYSIS_SCOPE_FORBIDDEN"
    VERSION_UNSUPPORTED = "REFERENCE_ANALYSIS_VERSION_UNSUPPORTED"
    REFERENCE_MISMATCH = "REFERENCE_ANALYSIS_REFERENCE_MISMATCH"
    PATH_FORBIDDEN = "REFERENCE_ANALYSIS_PATH_FORBIDDEN"
    OUTPUT_CONFLICT = "REFERENCE_ANALYSIS_OUTPUT_CONFLICT"
    CANCELLED = "REFERENCE_ANALYSIS_CANCELLED"
    WRITE_FAILED = "REFERENCE_ANALYSIS_WRITE_FAILED"


_SENSITIVE_KEY = re.compile(r"(?i)(token|secret|password|credential|authorization|api[_-]?key)")
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_LABEL = re.compile(r"(?i)\b(token|secret|password|credential|authorization|api[_-]?key)\s*(?:[:=]\s*|\s+)\S+")


def _sanitize_text(value: str) -> str:
    value = _BEARER.sub("Bearer [REDACTED]", value)
    return _LABEL.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)


def _sanitize(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(nested_key): _sanitize(nested, key=str(nested_key)) for nested_key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


class SkillError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        field_paths: tuple[str, ...] = (),
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        message = _sanitize_text(message)
        super().__init__(message)
        self.code = code
        self.message = message
        self.field_paths = field_paths
        self.retryable = retryable
        self.details = _sanitize(details or {})

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "field_paths": list(self.field_paths),
            "retryable": self.retryable,
            "details": self.details,
        }
