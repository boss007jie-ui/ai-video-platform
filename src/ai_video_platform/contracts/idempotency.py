"""In-memory idempotency and replay guard for synthetic/offline use."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import ContractError, ErrorCategory, ErrorCode
from .serialization import freeze_json


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ReplayStatus(str, Enum):
    RECORDED = "recorded"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class ReplayResult:
    status: ReplayStatus
    digest: str
    outcome: Any


class IdempotencyLedger:
    def __init__(self) -> None:
        self._records: dict[str, ReplayResult] = {}

    def check_or_record(self, key: str, digest: str, outcome: Any) -> ReplayResult:
        if not key or not _DIGEST.fullmatch(digest):
            raise ContractError(
                ErrorCode.CONTRACT_VALIDATION_FAILED,
                ErrorCategory.VALIDATION,
                "Idempotency key and lowercase SHA-256 digest are required",
                field_paths=("idempotency_key", "payload_digest"),
            )
        existing = self._records.get(key)
        if existing is None:
            result = ReplayResult(ReplayStatus.RECORDED, digest, freeze_json(outcome))
            self._records[key] = result
            return result
        if existing.digest != digest:
            raise ContractError(
                ErrorCode.CONTRACT_DUPLICATE_MISMATCH,
                ErrorCategory.CONFLICT,
                "Idempotency key was reused with a different payload digest",
                field_paths=("idempotency_key", "payload_digest"),
            )
        return ReplayResult(ReplayStatus.REPLAYED, existing.digest, existing.outcome)

    def get(self, key: str) -> ReplayResult:
        return self._records[key]
