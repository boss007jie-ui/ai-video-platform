"""Stable redacted errors for Video Generation."""

from __future__ import annotations

from enum import Enum
import re
from typing import Any, Mapping


class GenerationErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    PACKAGE_INVALID = "PACKAGE_INVALID"
    PACKAGE_VERSION_UNSUPPORTED = "PACKAGE_VERSION_UNSUPPORTED"
    PACKAGE_TAMPERED = "PACKAGE_TAMPERED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_NOT_EFFECTIVE = "APPROVAL_NOT_EFFECTIVE"
    APPROVAL_SUBJECT_MISMATCH = "APPROVAL_SUBJECT_MISMATCH"
    BUDGET_INVALID = "BUDGET_INVALID"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    PROVIDER_BINDING_INVALID = "PROVIDER_BINDING_INVALID"
    CREDENTIAL_REFERENCE_INVALID = "CREDENTIAL_REFERENCE_INVALID"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"


_SENSITIVE_KEY = re.compile(r"(?i)(authorization|credential|api[_-]?key|token|secret|password|private[_-]?key|traceback|stack)")
_SENSITIVE_VALUE = re.compile(r"(?:\bsk-[A-Za-z0-9_-]{20,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")


def _sanitize(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(nested_key): _sanitize(nested, key=str(nested_key)) for nested_key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        return "[REDACTED]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


class GenerationError(ValueError):
    def __init__(
        self,
        code: GenerationErrorCode,
        message: str,
        *,
        field_paths: tuple[str, ...] = (),
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field_paths = field_paths
        self.details = _sanitize(details or {})
        self.retryable = retryable

    def to_dict(self) -> dict[str, object]:
        authorization_codes = {
            GenerationErrorCode.APPROVAL_REQUIRED,
            GenerationErrorCode.APPROVAL_NOT_EFFECTIVE,
            GenerationErrorCode.APPROVAL_SUBJECT_MISMATCH,
            GenerationErrorCode.CREDENTIAL_REFERENCE_INVALID,
        }
        category = "authorization" if self.code in authorization_codes else "validation"
        return {
            "code": self.code.value,
            "category": category,
            "retryable": self.retryable,
            "message": self.message,
            "field_paths": list(self.field_paths),
            "details": _sanitize(self.details),
        }
