from __future__ import annotations

from copy import deepcopy
import unittest

from ai_video_platform.skills.qa_review import EvaluationThresholds, ReviewOutcome, evaluate_dataset
from tests.skills.qa_review.test_qa_review_interface import valid_request


class QAReviewEvaluationTests(unittest.TestCase):
    def test_versioned_dataset_measures_false_positive_and_false_negative_rates(self) -> None:
        pass_case = valid_request()
        fail_case = deepcopy(valid_request())
        fail_case["execution_id"] = "exec-qa-fail"
        fail_case["subject"]["quality"]["artifact_score"] = 0.50
        review_case = deepcopy(valid_request())
        review_case["execution_id"] = "exec-qa-review"
        del review_case["subject"]["quality"]["sharpness"]
        dataset = {
            "schema_version": "1.0.0",
            "dataset_version": "qa-eval-v1",
            "thresholds": {
                "max_false_positive_rate": 0.0,
                "max_false_negative_rate": 0.0,
                "max_needs_review_rate": 0.34,
            },
            "cases": [
                {"case_id": "pass", "expected_outcome": "pass", "request": pass_case},
                {"case_id": "fail", "expected_outcome": "fail", "request": fail_case},
                {"case_id": "review", "expected_outcome": "needs-review", "request": review_case},
            ],
        }

        report = evaluate_dataset(dataset)

        self.assertEqual(report.dataset_version, "qa-eval-v1")
        self.assertEqual(report.case_count, 3)
        self.assertEqual(report.false_positive_rate, 0.0)
        self.assertEqual(report.false_negative_rate, 0.0)
        self.assertEqual(report.needs_review_rate, 1 / 3)
        self.assertTrue(report.thresholds_met)
        self.assertEqual(
            tuple(item.actual_outcome for item in report.case_results),
            (ReviewOutcome.PASS, ReviewOutcome.FAIL, ReviewOutcome.NEEDS_REVIEW),
        )

    def test_thresholds_are_immutable_and_validate_ranges(self) -> None:
        thresholds = EvaluationThresholds.from_mapping(
            {
                "max_false_positive_rate": 0.1,
                "max_false_negative_rate": 0.2,
                "max_needs_review_rate": 0.3,
            }
        )

        with self.assertRaises(AttributeError):
            thresholds.max_false_positive_rate = 0.9
        with self.assertRaises(ValueError):
            EvaluationThresholds.from_mapping({"max_false_positive_rate": 1.1})


if __name__ == "__main__":
    unittest.main()
