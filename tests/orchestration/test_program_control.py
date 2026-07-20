from __future__ import annotations

import unittest

from ai_video_platform.contracts.errors import ContractError, ErrorCode
from ai_video_platform.orchestration.hermes.program_control import (
    ProgramControl,
    WorkItem,
    WorkStatus,
)


def _work_item(*, authorization_refs: tuple[str, ...] = ("FTG-0-20260720-001",)) -> WorkItem:
    return WorkItem(
        work_item_id="FT-00-001",
        workline_id="codex-00",
        owner="Codex-00",
        objective="Build the shared Fast Track control surface",
        owned_paths=("src/ai_video_platform/orchestration/hermes/",),
        forbidden_paths=("src/ai_video_platform/skills/*/application/",),
        gate_required="FTG-1",
        authorization_refs=authorization_refs,
        test_commands=("python tools/run_offline_tests.py",),
        rollback="git revert <commit>",
    )


class ProgramControlTests(unittest.TestCase):
    def test_register_dispatch_and_evidence_are_machine_readable(self) -> None:
        control = ProgramControl()
        registered = control.register_work_item(_work_item())
        dispatched = control.dispatch_work_item("FT-00-001")
        evidence = control.record_evidence("FT-00-001", "commit:a" + "0" * 39)

        self.assertEqual(registered.to_dict()["status"], "READY")
        self.assertEqual(dispatched.status, WorkStatus.IN_PROGRESS)
        self.assertEqual(evidence.to_dict()["evidence_refs"], ["commit:a" + "0" * 39])

    def test_registration_fails_closed_without_fast_track_authorization(self) -> None:
        with self.assertRaises(ContractError) as captured:
            ProgramControl().register_work_item(_work_item(authorization_refs=()))

        self.assertEqual(captured.exception.code, ErrorCode.WORK_ITEM_AUTHORIZATION_REQUIRED)


if __name__ == "__main__":
    unittest.main()
