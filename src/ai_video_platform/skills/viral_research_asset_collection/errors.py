"""Stable, redacted errors owned by the Viral Research Skill."""

from __future__ import annotations

from enum import Enum
import re
from typing import Mapping, Any


class ErrorCode(str, Enum):
    VALIDATION_FAILED = "VIRAL_RESEARCH_VALIDATION_FAILED"
    BUDGET_EXCEEDED = "VIRAL_RESEARCH_BUDGET_EXCEEDED"
    REQUEST_EXPIRED = "VIRAL_RESEARCH_REQUEST_EXPIRED"
    CANCELLED = "VIRAL_RESEARCH_CANCELLED"
    IDEMPOTENCY_CONFLICT = "VIRAL_RESEARCH_IDEMPOTENCY_CONFLICT"
    PROVIDER_FORBIDDEN = "VIRAL_RESEARCH_PROVIDER_FORBIDDEN"
    PROVIDER_FAILURE = "VIRAL_RESEARCH_PROVIDER_FAILURE"
    DOWNLOAD_FORBIDDEN = "VIRAL_RESEARCH_DOWNLOAD_FORBIDDEN"
    PATH_FORBIDDEN = "VIRAL_RESEARCH_PATH_FORBIDDEN"
    RIGHTS_FORBIDDEN = "VIRAL_RESEARCH_RIGHTS_FORBIDDEN"
    STORAGE_CONFLICT = "VIRAL_RESEARCH_STORAGE_CONFLICT"
    RETENTION_EXTENSION_FORBIDDEN = "VIRAL_RESEARCH_RETENTION_EXTENSION_FORBIDDEN"


_SENSITIVE = re.compile(r"(?i)(token|secret|password|credential|authorization|api[_-]?key)")
_SENSITIVE_MESSAGE = re.compile(r"(?i)\b(token|secret|password|credential|authorization|api[_-]?key)\s*[:=]\s*\S+")


def _sanitize_message(message: str) -> str:
    return _SENSITIVE_MESSAGE.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)


def _redact(details: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in details.items():
        if _SENSITIVE.search(str(key)):
            result[str(key)] = "[REDACTED]"
        elif isinstance(value, Mapping):
            result[str(key)] = _redact(value)
        elif value is None or isinstance(value, (str, int, float, bool)):
            result[str(key)] = value
        else:
            result[str(key)] = f"<{type(value).__name__}>"
    return result


class SkillError(Exception):
    """Machine-readable failure that never exposes sensitive detail values."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        field_paths: tuple[str, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        message = _sanitize_message(message)
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.field_paths = field_paths
        self.details = _redact(details or {})

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "field_paths": list(self.field_paths),
            "details": dict(self.details),
        }
