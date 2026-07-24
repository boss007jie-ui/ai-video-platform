from __future__ import annotations

import json
from pathlib import Path
import unittest

from ai_video_platform.skills.qa_review import ReviewOutcome, ReviewRequest, review
from tests.skills.qa_review.test_storyboard_artifact_chain import _apply_mutation, valid_composition_request


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_FIXTURE = PROJECT_ROOT / "fixtures" / "golden" / "qa_review" / "storyboard-chain-cases-v1.json"


class StoryboardArtifactChainGoldenTests(unittest.TestCase):
    def test_locked_failure_codes_and_outcomes_have_zero_false_positive_or_negative(self) -> None:
        fixture = json.loads(CASES_FIXTURE.read_text(encoding="utf-8"))
        false_positives = 0
        false_negatives = 0

        for case in fixture["cases"]:
            with self.subTest(case=case["case_id"]):
                request = valid_composition_request()
                request["execution_id"] = f"golden-{case['case_id']}"
                _apply_mutation(request, case["mutation"])
                result = review(ReviewRequest.from_mapping(request))
                expected = ReviewOutcome(case["expected_outcome"])
                false_positives += expected is ReviewOutcome.PASS and result.outcome is ReviewOutcome.FAIL
                false_negatives += expected is ReviewOutcome.FAIL and result.outcome is ReviewOutcome.PASS
                self.assertEqual(result.outcome, expected)
                expected_code = case.get("expected_code")
                if expected_code:
                    matching = [
                        issue for issue in result.human_review_package["issues"]
                        if issue["code"] == expected_code
                    ]
                    self.assertTrue(matching)
                    self.assertTrue(matching[0]["offending_artifact"])
                    self.assertTrue(matching[0]["owning_producer"])

        self.assertEqual(false_positives, 0)
        self.assertEqual(false_negatives, 0)
        self.assertEqual(fixture["thresholds"]["max_false_positive_rate"], 0.0)
        self.assertEqual(fixture["thresholds"]["max_false_negative_rate"], 0.0)
        self.assertEqual(fixture["provider_calls"], 0)


if __name__ == "__main__":
    unittest.main()
