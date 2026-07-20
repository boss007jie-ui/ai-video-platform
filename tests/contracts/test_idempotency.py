from __future__ import annotations

import unittest

from ai_video_platform.contracts.errors import ContractError, ErrorCode
from ai_video_platform.contracts.idempotency import IdempotencyLedger, ReplayStatus


class IdempotencyTests(unittest.TestCase):
    def test_first_record_and_exact_replay_are_distinct_outcomes(self) -> None:
        ledger = IdempotencyLedger()

        first = ledger.check_or_record("key-001", "sha256:" + "a" * 64, {"ok": True})
        replay = ledger.check_or_record("key-001", "sha256:" + "a" * 64, {"ignored": True})

        self.assertEqual(first.status, ReplayStatus.RECORDED)
        self.assertEqual(replay.status, ReplayStatus.REPLAYED)
        self.assertEqual(replay.outcome, {"ok": True})

    def test_same_key_with_different_digest_is_rejected_without_overwrite(self) -> None:
        ledger = IdempotencyLedger()
        ledger.check_or_record("key-001", "sha256:" + "a" * 64, {"ok": True})

        with self.assertRaises(ContractError) as captured:
            ledger.check_or_record("key-001", "sha256:" + "b" * 64, {"ok": False})

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_DUPLICATE_MISMATCH)
        self.assertEqual(ledger.get("key-001").outcome, {"ok": True})

    def test_recorded_outcome_is_an_immutable_snapshot(self) -> None:
        ledger = IdempotencyLedger()
        outcome = {"items": ["one"]}

        recorded = ledger.check_or_record("key-001", "sha256:" + "a" * 64, outcome)
        outcome["items"].append("two")

        self.assertEqual(recorded.outcome["items"], ("one",))
        with self.assertRaises(TypeError):
            recorded.outcome["new"] = True

    def test_invalid_idempotency_identity_is_rejected(self) -> None:
        ledger = IdempotencyLedger()

        with self.assertRaises(ContractError) as captured:
            ledger.check_or_record("", "not-a-digest", {"ok": False})

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)

        for invalid_digest in (
            "sha256:" + "g" * 64,
            "sha256:" + "A" * 64,
        ):
            with self.subTest(invalid_digest=invalid_digest):
                with self.assertRaises(ContractError) as malformed:
                    ledger.check_or_record("key-001", invalid_digest, {"ok": False})

                self.assertEqual(malformed.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)


if __name__ == "__main__":
    unittest.main()
