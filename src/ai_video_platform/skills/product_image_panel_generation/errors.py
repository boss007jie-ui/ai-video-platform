"""Stable, sanitized public errors for image and panel generation."""

from __future__ import annotations

from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping


_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|api[_-]?key|token|secret|password|credential|private[_-]?key|traceback|stack|provider_payload)"
)
_SENSITIVE_VALUE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{20,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


class ImagePanelErrorCode(str, Enum):
    CONTRACT_INVALID = "IMAGE_PANEL_CONTRACT_INVALID"
    REQUEST_HASH_MISMATCH = "IMAGE_PANEL_REQUEST_HASH_MISMATCH"
    PRODUCT_CONTEXT_REQUIRED = "IMAGE_PANEL_PRODUCT_CONTEXT_REQUIRED"
    PRODUCT_IDENTITY_MISMATCH = "IMAGE_PANEL_PRODUCT_IDENTITY_MISMATCH"
    ASSET_NOT_APPROVED = "IMAGE_PANEL_ASSET_NOT_APPROVED"
    REFERENCE_RIGHTS_UNCONFIRMED = "IMAGE_PANEL_REFERENCE_RIGHTS_UNCONFIRMED"
    BUDGET_REQUIRED = "IMAGE_PANEL_BUDGET_REQUIRED"
    BUDGET_EXCEEDED = "IMAGE_PANEL_BUDGET_EXCEEDED"
    DIMENSIONS_INVALID = "IMAGE_PANEL_DIMENSIONS_INVALID"
    MODEL_PROFILE_INVALID = "IMAGE_PANEL_MODEL_PROFILE_INVALID"
    APPROVAL_REQUIRED = "IMAGE_PANEL_APPROVAL_REQUIRED"
    APPROVAL_NOT_EFFECTIVE = "IMAGE_PANEL_APPROVAL_NOT_EFFECTIVE"
    APPROVAL_SUBJECT_MISMATCH = "IMAGE_PANEL_APPROVAL_SUBJECT_MISMATCH"
    STALE_INPUT = "IMAGE_PANEL_STALE_INPUT"
    SKILL_BINDING_INVALID = "IMAGE_PANEL_SKILL_BINDING_INVALID"
    IDEMPOTENCY_CONFLICT = "IMAGE_PANEL_IDEMPOTENCY_CONFLICT"
    IDEMPOTENCY_IN_PROGRESS = "IMAGE_PANEL_IDEMPOTENCY_IN_PROGRESS"
    CONCURRENCY_LIMIT_EXCEEDED = "IMAGE_PANEL_CONCURRENCY_LIMIT_EXCEEDED"
    PROVIDER_BYPASS_FORBIDDEN = "IMAGE_PANEL_PROVIDER_BYPASS_FORBIDDEN"
    PROVIDER_NOT_AUTHORIZED = "IMAGE_PANEL_PROVIDER_NOT_AUTHORIZED"
    PROVIDER_FAILED = "IMAGE_PANEL_PROVIDER_FAILED"
    PROVIDER_TIMEOUT = "IMAGE_PANEL_PROVIDER_TIMEOUT"
    CANCELLED = "IMAGE_PANEL_CANCELLED"


def _sanitize(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _sanitize(v, key=str(k)) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_sanitize(item) for item in value)
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        return "[REDACTED]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


class ImagePanelError(Exception):
    """Machine-readable failure with no secret or Provider-payload disclosure."""

    def __init__(
        self,
        code: ImagePanelErrorCode,
        message: str,
        *,
        category: str = "validation",
        retryable: bool = False,
        field_paths: tuple[str, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.category = category
        self.retryable = retryable
        self.field_paths = tuple(field_paths)
        self.details = _sanitize(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "category": self.category,
            "retryable": self.retryable,
            "message": self.message,
            "field_paths": list(self.field_paths),
            "details": _json_value(self.details),
        }
