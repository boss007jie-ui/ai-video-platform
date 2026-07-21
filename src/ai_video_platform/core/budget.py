"""Fail-closed request and cost budget accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ai_video_platform.contracts.errors import ContractError, ErrorCategory, ErrorCode


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    max_requests: int
    max_cost: Decimal

    def __post_init__(self) -> None:
        if self.max_requests < 0 or self.max_cost < 0 or not self.max_cost.is_finite():
            raise ValueError("Budget limits must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    request_count: int
    reserved_cost: Decimal
    remaining_requests: int
    remaining_cost: Decimal


class BudgetLedger:
    """In-memory reservation ledger used before any provider boundary."""

    def __init__(self, policy: BudgetPolicy) -> None:
        self.policy = policy
        self._reservations: dict[str, Decimal] = {}

    def snapshot(self) -> BudgetSnapshot:
        reserved = sum(self._reservations.values(), start=Decimal("0"))
        return BudgetSnapshot(
            request_count=len(self._reservations),
            reserved_cost=reserved,
            remaining_requests=self.policy.max_requests - len(self._reservations),
            remaining_cost=self.policy.max_cost - reserved,
        )

    def reserve(self, *, request_id: str, estimated_cost: Decimal) -> BudgetSnapshot:
        if not request_id or estimated_cost < 0 or not estimated_cost.is_finite():
            raise ContractError(
                ErrorCode.CONTRACT_VALIDATION_FAILED,
                ErrorCategory.VALIDATION,
                "request_id and a finite non-negative estimated_cost are required",
                field_paths=("request_id", "estimated_cost"),
            )
        existing = self._reservations.get(request_id)
        if existing is not None:
            if existing != estimated_cost:
                raise ContractError(
                    ErrorCode.CONTRACT_DUPLICATE_MISMATCH,
                    ErrorCategory.CONFLICT,
                    "Budget request identity was reused with a different estimate",
                    field_paths=("request_id", "estimated_cost"),
                )
            return self.snapshot()
        current = self.snapshot()
        if current.request_count + 1 > self.policy.max_requests or current.reserved_cost + estimated_cost > self.policy.max_cost:
            raise ContractError(
                ErrorCode.BUDGET_EXCEEDED,
                ErrorCategory.AUTHORIZATION,
                "The configured request or cost budget would be exceeded",
                field_paths=("estimated_cost",),
                details={
                    "remaining_requests": current.remaining_requests,
                    "remaining_cost": str(current.remaining_cost),
                },
            )
        self._reservations[request_id] = estimated_cost
        return self.snapshot()
