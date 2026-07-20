from __future__ import annotations

import unittest

from ai_video_platform.contracts.registry import (
    ENVELOPE_SCHEMA_ID,
    FOUNDATION_CONTRACT_IDS,
)


class FoundationRegistryTests(unittest.TestCase):
    def test_registry_is_exactly_one_envelope_and_eleven_payloads(self) -> None:
        self.assertEqual(ENVELOPE_SCHEMA_ID, "avp.schema.contract-envelope")
        self.assertEqual(
            FOUNDATION_CONTRACT_IDS,
            (
                "avp.contract.task-spec",
                "avp.contract.task-context",
                "avp.contract.skill-execution-event",
                "avp.contract.product-context-bundle",
                "avp.contract.product-review-context",
                "avp.contract.feedback-event",
                "avp.contract.rule-ref",
                "avp.contract.asset-manifest",
                "avp.contract.reference-manifest",
                "avp.contract.review-decision",
                "avp.contract.approval-record",
            ),
        )


if __name__ == "__main__":
    unittest.main()
