from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from ai_video_platform.skills.qa_review import QAError, QAErrorCode, ReviewOutcome, ReviewRequest, evaluate_dataset, review


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = PROJECT_ROOT / "fixtures" / "golden" / "qa_review"


def deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        elif value == "__DELETE__":
            result.pop(key, None)
        else:
            result[key] = deepcopy(value)
    return result


class QAGoldenScenarioTests(unittest.TestCase):
    def test_locked_evaluation_fixture_meets_false_positive_negative_thresholds(self) -> None:
        dataset = json.loads((GOLDEN_ROOT / "evaluation-v1.json").read_text(encoding="utf-8"))

        report = evaluate_dataset(dataset)

        self.assertEqual(report.dataset_version, "qa-eval-v1")
        self.assertEqual(report.false_positive_rate, 0.0)
        self.assertEqual(report.false_negative_rate, 0.0)
        self.assertTrue(report.thresholds_met)

    def test_standalone_optional_partial_stale_cancellation_and_recovery(self) -> None:
        fixture = json.loads((GOLDEN_ROOT / "scenarios-v1.json").read_text(encoding="utf-8"))
        seen: set[str] = set()

        for scenario in fixture["scenarios"]:
            with self.subTest(scenario=scenario["scenario_id"]):
                seen.add(scenario["scenario_id"])
                request = ReviewRequest.from_mapping(
                    deep_merge(fixture["base_request"], scenario.get("overrides", {}))
                )
                expected_error = scenario.get("expected_error")
                if expected_error:
                    with self.assertRaises(QAError) as captured:
                        review(request)
                    self.assertEqual(captured.exception.code.value, expected_error)
                    continue
                result = review(request)
                self.assertEqual(result.outcome, ReviewOutcome(scenario["expected_outcome"]))
                expected_retry = scenario.get("expected_retry_of")
                if expected_retry:
                    self.assertEqual(
                        result.skill_execution_event["retry_of_execution_id"],
                        expected_retry,
                    )

        self.assertEqual(
            seen,
            {
                "standalone",
                "optional-pairing",
                "partial-failure",
                "stale-contract",
                "cancellation",
                "recovery",
            },
        )


if __name__ == "__main__":
    unittest.main()
