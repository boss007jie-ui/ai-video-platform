"""Append-only provider-operation state ledger with explicit transitions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from ai_video_platform.contracts.errors import ContractError, ErrorCategory, ErrorCode


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class OperationState(str, Enum):
    PREPARED = "prepared"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TRANSITIONS = {
    None: {OperationState.PREPARED},
    OperationState.PREPARED: {OperationState.SUBMITTED, OperationState.CANCELLED},
    OperationState.SUBMITTED: {OperationState.RUNNING, OperationState.SUCCEEDED, OperationState.FAILED, OperationState.CANCELLED},
    OperationState.RUNNING: {OperationState.SUCCEEDED, OperationState.FAILED, OperationState.CANCELLED},
    OperationState.SUCCEEDED: set(),
    OperationState.FAILED: set(),
    OperationState.CANCELLED: set(),
}


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    sequence: int
    state: OperationState
    request_digest: str


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    operation_id: str
    state: OperationState
    request_digest: str
    history: tuple[LedgerEntry, ...]


class OperationLedger:
    def __init__(self) -> None:
        self._entries: dict[str, list[LedgerEntry]] = {}

    def append(
        self,
        *,
        operation_id: str,
        request_digest: str,
        state: OperationState,
    ) -> OperationSnapshot:
        if not operation_id or not _DIGEST.fullmatch(request_digest):
            raise ContractError(
                ErrorCode.CONTRACT_VALIDATION_FAILED,
                ErrorCategory.VALIDATION,
                "operation_id and lowercase SHA-256 request_digest are required",
                field_paths=("operation_id", "request_digest"),
            )
        entries = self._entries.setdefault(operation_id, [])
        if entries and entries[-1].request_digest != request_digest:
            raise ContractError(
                ErrorCode.CONTRACT_DUPLICATE_MISMATCH,
                ErrorCategory.CONFLICT,
                "Operation identity was reused with a different request digest",
                field_paths=("operation_id", "request_digest"),
            )
        current = entries[-1].state if entries else None
        if current == state:
            return self.snapshot(operation_id)
        if state not in _TRANSITIONS[current]:
            raise ContractError(
                ErrorCode.LEDGER_TRANSITION_INVALID,
                ErrorCategory.STATE,
                "Operation ledger transition is not allowed",
                field_paths=("state",),
                details={"current_state": current.value if current else None, "requested_state": state.value},
            )
        entries.append(LedgerEntry(len(entries) + 1, state, request_digest))
        return self.snapshot(operation_id)

    def history(self, operation_id: str) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries.get(operation_id, ()))

    def snapshot(self, operation_id: str) -> OperationSnapshot:
        history = self.history(operation_id)
        if not history:
            raise KeyError(operation_id)
        return OperationSnapshot(operation_id, history[-1].state, history[-1].request_digest, history)
