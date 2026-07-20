"""Small public Hermes program-control interface.

This module records control-plane state only.  It does not import or execute a
business Skill, mutate Git, approve gates, or turn evidence into a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from ai_video_platform.contracts.errors import ContractError, ErrorCategory, ErrorCode


class WorkStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    REVIEW = "REVIEW"
    RC_OFFLINE = "RC_OFFLINE"
    BLOCKED = "BLOCKED"
    RC_PROVIDER_PENDING = "RC_PROVIDER_PENDING"
    PRODUCTION_READY = "PRODUCTION_READY"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class WorkItem:
    work_item_id: str
    workline_id: str
    owner: str
    objective: str
    owned_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    gate_required: str
    authorization_refs: tuple[str, ...]
    test_commands: tuple[str, ...]
    rollback: str
    skill_ids: tuple[str, ...] = ()
    input_contracts: tuple[str, ...] = ()
    output_contracts: tuple[str, ...] = ()
    contract_request_refs: tuple[str, ...] = ()
    dependency_ids: tuple[str, ...] = ()
    legacy_dv_case_refs: tuple[str, ...] = ()
    catpaw_request_refs: tuple[str, ...] = ()
    adoption_proposal_refs: tuple[str, ...] = ()
    expected_results: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    risk_level: str = "medium"
    provider_smoke_required: bool = False
    status: WorkStatus = WorkStatus.READY
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.work_item_id or not self.workline_id or not self.owner or not self.objective:
            raise ValueError("work item identity, owner, and objective are required")
        object.__setattr__(self, "owned_paths", tuple(self.owned_paths))
        object.__setattr__(self, "forbidden_paths", tuple(self.forbidden_paths))
        object.__setattr__(self, "authorization_refs", tuple(self.authorization_refs))
        object.__setattr__(self, "test_commands", tuple(self.test_commands))


@dataclass(frozen=True, slots=True)
class ControlResult:
    operation: str
    work_item_id: str
    status: WorkStatus
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "operation": self.operation,
            "work_item_id": self.work_item_id,
            "status": self.status.value,
            "evidence_refs": list(self.evidence_refs),
        }


class ProgramControl:
    def __init__(self) -> None:
        self._items: dict[str, WorkItem] = {}

    def register_work_item(self, item: WorkItem) -> ControlResult:
        if not any(reference.startswith("FTG-0-") for reference in item.authorization_refs):
            raise ContractError(
                ErrorCode.WORK_ITEM_AUTHORIZATION_REQUIRED,
                ErrorCategory.AUTHORIZATION,
                "A valid FTG-0 authorization reference is required",
                field_paths=("authorization_refs",),
            )
        existing = self._items.get(item.work_item_id)
        if existing is not None and existing != item:
            raise ContractError(
                ErrorCode.WORK_ITEM_CONFLICT,
                ErrorCategory.CONFLICT,
                "Work item identity is already registered with different content",
                field_paths=("work_item_id",),
            )
        if existing is None:
            self._items[item.work_item_id] = item
        return self._result("register-work-item", self._items[item.work_item_id])

    def dispatch_work_item(self, work_item_id: str) -> ControlResult:
        item = self.get(work_item_id)
        if item.status is not WorkStatus.READY:
            raise self._state_error(item, "Only READY work may be dispatched")
        if item.provider_smoke_required and not any(ref.startswith("FTG-P-") for ref in item.authorization_refs):
            raise ContractError(
                ErrorCode.WORK_ITEM_AUTHORIZATION_REQUIRED,
                ErrorCategory.AUTHORIZATION,
                "Provider work requires a separate FTG-P authorization reference",
                field_paths=("authorization_refs",),
            )
        updated = replace(item, status=WorkStatus.IN_PROGRESS)
        self._items[work_item_id] = updated
        return self._result("dispatch-work-item", updated)

    def record_evidence(self, work_item_id: str, evidence_ref: str) -> ControlResult:
        item = self.get(work_item_id)
        if not evidence_ref:
            raise ValueError("evidence_ref is required")
        refs = item.evidence_refs if evidence_ref in item.evidence_refs else (*item.evidence_refs, evidence_ref)
        updated = replace(item, evidence_refs=refs)
        self._items[work_item_id] = updated
        return self._result("record-evidence", updated)

    def request_gate_review(self, work_item_id: str) -> ControlResult:
        item = self.get(work_item_id)
        if item.status is not WorkStatus.IN_PROGRESS or not item.evidence_refs:
            raise self._state_error(item, "Gate review requires IN_PROGRESS work with evidence")
        updated = replace(item, status=WorkStatus.REVIEW)
        self._items[work_item_id] = updated
        return self._result("request-gate-review", updated)

    def get(self, work_item_id: str) -> WorkItem:
        try:
            return self._items[work_item_id]
        except KeyError as exc:
            raise KeyError(f"Unknown work item: {work_item_id}") from exc

    def publish_program_status(self) -> tuple[ControlResult, ...]:
        return tuple(self._result("publish-program-status", self._items[key]) for key in sorted(self._items))

    @staticmethod
    def _result(operation: str, item: WorkItem) -> ControlResult:
        return ControlResult(operation, item.work_item_id, item.status, item.evidence_refs)

    @staticmethod
    def _state_error(item: WorkItem, message: str) -> ContractError:
        return ContractError(
            ErrorCode.WORK_ITEM_STATE_INVALID,
            ErrorCategory.STATE,
            message,
            field_paths=("status",),
            details={"status": item.status.value},
        )
