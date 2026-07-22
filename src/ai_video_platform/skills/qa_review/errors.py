"""Stable, sanitized QA / Review public errors."""

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
        return MappingProxyType(
            {str(nested_key): _sanitize(nested, key=str(nested_key)) for nested_key, nested in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_sanitize(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


def _to_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_json(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_to_json(item) for item in value]
    return value


class QAErrorCode(str, Enum):
    QA_INPUT_INVALID = "QA_INPUT_INVALID"
    QA_SCHEMA_UNSUPPORTED = "QA_SCHEMA_UNSUPPORTED"
    QA_COMMAND_UNSUPPORTED = "QA_COMMAND_UNSUPPORTED"
    QA_CRITERION_FORBIDDEN = "QA_CRITERION_FORBIDDEN"
    QA_OUTPUT_PATH_FORBIDDEN = "QA_OUTPUT_PATH_FORBIDDEN"
    QA_CANCELLED = "QA_CANCELLED"


class QAError(Exception):
    def __init__(
        self,
        code: QAErrorCode,
        category: str,
        message: str,
        *,
        field_paths: tuple[str, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.message = message
        self.field_paths = tuple(field_paths)
        self.details = _sanitize(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "category": self.category,
            "retryable": False,
            "message": self.message,
            "field_paths": list(self.field_paths),
            "details": _to_json(self.details),
        }
