from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from ai_video_platform.contracts.errors import ContractError, ErrorCode
from ai_video_platform.core.audit import InMemoryAuditLedger
from ai_video_platform.core.budget import BudgetLedger, BudgetPolicy
from ai_video_platform.core.ledger import OperationLedger, OperationState


class CoreControlTests(unittest.TestCase):
    def test_audit_ledger_appends_immutable_structured_events(self) -> None:
        ledger = InMemoryAuditLedger()
        details = {"result": "accepted", "nested": {"count": 1}}

        event = ledger.record(
            correlation_id="corr-001",
            event_type="work-item.registered",
            actor="hermes",
            occurred_at=datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc),
            details=details,
        )
        details["nested"]["count"] = 99

        self.assertEqual(event.sequence, 1)
        self.assertEqual(event.details["nested"]["count"], 1)
        self.assertEqual(ledger.events("corr-001"), (event,))

    def test_budget_ledger_fails_closed_without_mutating_totals(self) -> None:
        ledger = BudgetLedger(BudgetPolicy(max_requests=1, max_cost=Decimal("2.50")))
        first = ledger.reserve(request_id="request-1", estimated_cost=Decimal("1.25"))

        with self.assertRaises(ContractError) as captured:
            ledger.reserve(request_id="request-2", estimated_cost=Decimal("0.10"))

        self.assertEqual(captured.exception.code, ErrorCode.BUDGET_EXCEEDED)
        self.assertEqual(first.request_count, 1)
        self.assertEqual(ledger.snapshot(), first)

    def test_operation_ledger_rejects_transition_after_terminal_state(self) -> None:
        ledger = OperationLedger()
        digest = "sha256:" + "a" * 64
        ledger.append(operation_id="op-1", request_digest=digest, state=OperationState.PREPARED)
        terminal = ledger.append(operation_id="op-1", request_digest=digest, state=OperationState.CANCELLED)

        with self.assertRaises(ContractError) as captured:
            ledger.append(operation_id="op-1", request_digest=digest, state=OperationState.SUBMITTED)

        self.assertEqual(captured.exception.code, ErrorCode.LEDGER_TRANSITION_INVALID)
        self.assertEqual(ledger.history("op-1"), terminal.history)


if __name__ == "__main__":
    unittest.main()
