"""Stable public errors for offline video planning."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


class PlanningErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    STALE_INPUT_VERSION = "STALE_INPUT_VERSION"
    ASSET_MAPPING_MISSING = "ASSET_MAPPING_MISSING"
    ASSET_NOT_APPROVED = "ASSET_NOT_APPROVED"
    ASSET_MAPPING_AMBIGUOUS = "ASSET_MAPPING_AMBIGUOUS"
    CONTINUITY_CONFLICT = "CONTINUITY_CONFLICT"
    SHOT_SEQUENCE_INVALID = "SHOT_SEQUENCE_INVALID"
    PACKAGE_INVALID = "PACKAGE_INVALID"
    PACKAGE_TAMPERED = "PACKAGE_TAMPERED"
    PROVIDER_SUBMISSION_FORBIDDEN = "PROVIDER_SUBMISSION_FORBIDDEN"
    FIRST_FRAME_INELIGIBLE = "FIRST_FRAME_INELIGIBLE"
    REFERENCE_ROLE_FORBIDDEN = "REFERENCE_ROLE_FORBIDDEN"
    INVALID_SHOT_ORDER = "INVALID_SHOT_ORDER"


class PlanningError(ValueError):
    """Deterministic, machine-readable rejection with no implementation trace."""

    def __init__(
        self,
        code: PlanningErrorCode,
        message: str,
        *,
        field_paths: tuple[str, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field_paths = field_paths
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "category": "validation" if self.code is not PlanningErrorCode.CONTINUITY_CONFLICT else "conflict",
            "retryable": False,
            "message": self.message,
            "field_paths": list(self.field_paths),
            "details": dict(self.details),
        }
