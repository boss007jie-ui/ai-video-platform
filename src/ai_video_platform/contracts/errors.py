"""Stable, sanitized public error model for Shared Contracts."""

from __future__ import annotations

from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping


_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|api[_-]?key|token|secret|password|credential|private[_-]?key|traceback|stack)"
)
_SENSITIVE_VALUE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{20,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


def _sanitize_detail(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(nested_key): _sanitize_detail(nested, key=str(nested_key)) for nested_key, nested in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_sanitize_detail(item) for item in value)
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        return "[REDACTED]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


def _detail_to_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _detail_to_json(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_detail_to_json(item) for item in value]
    return value


class ErrorCategory(str, Enum):
    VALIDATION = "validation"
    COMPATIBILITY = "compatibility"
    REFERENCE = "reference"
    CONFLICT = "conflict"
    AUTHORIZATION = "authorization"
    STATE = "state"
    PROVIDER = "provider"
    INTERNAL = "internal"


class ErrorCode(str, Enum):
    CONTRACT_SCHEMA_UNSUPPORTED = "CONTRACT_SCHEMA_UNSUPPORTED"
    CONTRACT_VALIDATION_FAILED = "CONTRACT_VALIDATION_FAILED"
    CONTRACT_REFERENCE_UNRESOLVED = "CONTRACT_REFERENCE_UNRESOLVED"
    CONTRACT_DUPLICATE_MISMATCH = "CONTRACT_DUPLICATE_MISMATCH"
    CONTRACT_PRODUCER_FORBIDDEN = "CONTRACT_PRODUCER_FORBIDDEN"
    TASK_ID_CONFLICT = "TASK_ID_CONFLICT"
    TASK_TYPE_UNSUPPORTED = "TASK_TYPE_UNSUPPORTED"
    CONTEXT_REVISION_STALE = "CONTEXT_REVISION_STALE"
    TASK_STATE_TRANSITION_INVALID = "TASK_STATE_TRANSITION_INVALID"
    EVENT_SEQUENCE_CONFLICT = "EVENT_SEQUENCE_CONFLICT"
    PRODUCT_MATCH_AMBIGUOUS = "PRODUCT_MATCH_AMBIGUOUS"
    PRODUCT_CONTEXT_REQUIRED = "PRODUCT_CONTEXT_REQUIRED"
    PRODUCT_CONTEXT_INCOMPLETE = "PRODUCT_CONTEXT_INCOMPLETE"
    PRODUCT_CONTEXT_CONTAMINATED = "PRODUCT_CONTEXT_CONTAMINATED"
    PRODUCT_KNOWLEDGE_WRITE_FORBIDDEN = "PRODUCT_KNOWLEDGE_WRITE_FORBIDDEN"
    REVIEW_CONTEXT_STALE = "REVIEW_CONTEXT_STALE"
    RULE_SCOPE_INVALID = "RULE_SCOPE_INVALID"
    RULE_SCOPE_KEY_REQUIRED = "RULE_SCOPE_KEY_REQUIRED"
    RULE_REF_UNRESOLVED = "RULE_REF_UNRESOLVED"
    RULE_BINDING_MISMATCH = "RULE_BINDING_MISMATCH"
    RULE_NOT_EFFECTIVE = "RULE_NOT_EFFECTIVE"
    ASSET_HASH_MISMATCH = "ASSET_HASH_MISMATCH"
    ASSET_NOT_FOUND = "ASSET_NOT_FOUND"
    ASSET_NOT_APPROVED = "ASSET_NOT_APPROVED"
    ASSET_URI_FORBIDDEN = "ASSET_URI_FORBIDDEN"
    REFERENCE_HASH_MISMATCH = "REFERENCE_HASH_MISMATCH"
    REFERENCE_RIGHTS_UNCONFIRMED = "REFERENCE_RIGHTS_UNCONFIRMED"
    REFERENCE_ANALYSIS_UNRESOLVED = "REFERENCE_ANALYSIS_UNRESOLVED"
    REVIEW_SUBJECT_STALE = "REVIEW_SUBJECT_STALE"
    REVIEW_AUTHORITY_INSUFFICIENT = "REVIEW_AUTHORITY_INSUFFICIENT"
    REVIEW_EVIDENCE_INCOMPLETE = "REVIEW_EVIDENCE_INCOMPLETE"
    APPROVAL_AUTHORITY_INVALID = "APPROVAL_AUTHORITY_INVALID"
    APPROVAL_SUBJECT_MISMATCH = "APPROVAL_SUBJECT_MISMATCH"
    APPROVAL_NOT_EFFECTIVE = "APPROVAL_NOT_EFFECTIVE"
    NETWORK_ACCESS_FORBIDDEN = "NETWORK_ACCESS_FORBIDDEN"
    LEGACY_PATH_ACCESS_FORBIDDEN = "LEGACY_PATH_ACCESS_FORBIDDEN"
    SECRET_MATERIAL_FORBIDDEN = "SECRET_MATERIAL_FORBIDDEN"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    LEDGER_TRANSITION_INVALID = "LEDGER_TRANSITION_INVALID"


class ContractError(Exception):
    """Public failure with deterministic category, retryability, and fields."""

    def __init__(
        self,
        code: ErrorCode,
        category: ErrorCategory,
        message: str,
        *,
        retryable: bool = False,
        field_paths: tuple[str, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.retryable = retryable
        self.message = message
        self.field_paths = field_paths
        self.details = _sanitize_detail(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "category": self.category.value,
            "retryable": self.retryable,
            "message": self.message,
            "field_paths": list(self.field_paths),
            "details": _detail_to_json(self.details),
        }
