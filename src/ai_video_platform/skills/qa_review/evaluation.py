"""Versioned false-positive/false-negative evaluation for QA criteria."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .engine import review
from .models import ReviewOutcome, ReviewRequest


@dataclass(frozen=True, slots=True)
class EvaluationThresholds:
    max_false_positive_rate: float
    max_false_negative_rate: float
    max_needs_review_rate: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvaluationThresholds":
        names = (
            "max_false_positive_rate",
            "max_false_negative_rate",
            "max_needs_review_rate",
        )
        rates = {name: float(value.get(name, 0.0)) for name in names}
        if any(rate < 0.0 or rate > 1.0 for rate in rates.values()):
            raise ValueError("Evaluation thresholds must be between zero and one")
        return cls(**rates)


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    case_id: str
    expected_outcome: ReviewOutcome
    actual_outcome: ReviewOutcome


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    dataset_version: str
    case_count: int
    false_positive_rate: float
    false_negative_rate: float
    needs_review_rate: float
    thresholds_met: bool
    case_results: tuple[EvaluationCaseResult, ...]


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = deepcopy(value)
    return result


def evaluate_dataset(dataset: Mapping[str, Any]) -> EvaluationReport:
    if dataset.get("schema_version") != "1.0.0":
        raise ValueError("Evaluation dataset schema_version must be 1.0.0")
    dataset_version = dataset.get("dataset_version")
    if not isinstance(dataset_version, str) or not dataset_version:
        raise ValueError("Evaluation dataset_version is required")
    thresholds = EvaluationThresholds.from_mapping(dataset.get("thresholds", {}))
    raw_cases = dataset.get("cases")
    if not isinstance(raw_cases, (list, tuple)) or not raw_cases:
        raise ValueError("Evaluation dataset requires cases")

    base_request = dataset.get("base_request")
    results: list[EvaluationCaseResult] = []
    for item in raw_cases:
        if not isinstance(item, Mapping):
            raise ValueError("Evaluation cases must be objects")
        raw_request = item.get("request")
        if raw_request is None and isinstance(base_request, Mapping):
            overrides = item.get("overrides", {})
            if not isinstance(overrides, Mapping):
                raise ValueError("Evaluation case overrides must be an object")
            raw_request = _deep_merge(base_request, overrides)
        if not isinstance(raw_request, Mapping):
            raise ValueError("Evaluation case requires request or base_request")
        expected = ReviewOutcome(str(item["expected_outcome"]))
        actual = review(ReviewRequest.from_mapping(raw_request)).outcome
        results.append(
            EvaluationCaseResult(
                case_id=str(item["case_id"]),
                expected_outcome=expected,
                actual_outcome=actual,
            )
        )

    expected_pass = sum(item.expected_outcome is ReviewOutcome.PASS for item in results)
    expected_fail = sum(item.expected_outcome is ReviewOutcome.FAIL for item in results)
    false_positives = sum(
        item.expected_outcome is ReviewOutcome.PASS and item.actual_outcome is ReviewOutcome.FAIL
        for item in results
    )
    false_negatives = sum(
        item.expected_outcome is ReviewOutcome.FAIL and item.actual_outcome is ReviewOutcome.PASS
        for item in results
    )
    needs_review = sum(item.actual_outcome is ReviewOutcome.NEEDS_REVIEW for item in results)
    false_positive_rate = _rate(false_positives, expected_pass)
    false_negative_rate = _rate(false_negatives, expected_fail)
    needs_review_rate = _rate(needs_review, len(results))
    thresholds_met = (
        false_positive_rate <= thresholds.max_false_positive_rate
        and false_negative_rate <= thresholds.max_false_negative_rate
        and needs_review_rate <= thresholds.max_needs_review_rate
    )
    return EvaluationReport(
        dataset_version=dataset_version,
        case_count=len(results),
        false_positive_rate=false_positive_rate,
        false_negative_rate=false_negative_rate,
        needs_review_rate=needs_review_rate,
        thresholds_met=thresholds_met,
        case_results=tuple(results),
    )
