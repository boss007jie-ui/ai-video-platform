"""Deterministic clean-room QA checks and owned contract production."""

from __future__ import annotations

from typing import Any, Mapping
import os

from ai_video_platform.contracts.validation import validate_payload

from .errors import QAError, QAErrorCode
from .models import ReviewArtifacts, ReviewOutcome, ReviewRequest, _freeze
from .storyboard_chain import evaluate_storyboard_chain


SKILL_ID = "qa-review"
SKILL_VERSION = "1.0.0"
EVALUATED_AT = "2026-07-20T00:00:00Z"


def _issue(code: str, message: str, criterion_id: str, outcome: ReviewOutcome) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
        "criterion_id": criterion_id,
        "outcome": outcome.value,
    }


def review(request: ReviewRequest) -> ReviewArtifacts:
    if request.context.get("cancelled") is True:
        raise QAError(
            QAErrorCode.QA_CANCELLED,
            "state",
            "QA review was cancelled before evaluation",
            field_paths=("context.cancelled",),
        )
    subject = request.subject
    criteria = request.criteria
    context = request.context
    results: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []

    if request.command in {"review-artifact", "review-composition"}:
        results, issues = evaluate_storyboard_chain(request)
        return _build_artifacts(request, results, issues)

    def record(
        criterion_id: str,
        outcome: ReviewOutcome,
        *,
        code: str | None = None,
        message: str = "criterion satisfied",
    ) -> None:
        item: dict[str, Any] = {"criterion_id": criterion_id, "outcome": outcome.value}
        if code:
            item["code"] = code
        results.append(item)
        if outcome is not ReviewOutcome.PASS and code:
            issues.append(_issue(code, message, criterion_id, outcome))

    required_subject_fields = ("artifact_id", "artifact_type", "schema_version", "revision")
    missing_subject_fields = [name for name in required_subject_fields if subject.get(name) in (None, "")]
    if subject.get("contract_valid") is not True or missing_subject_fields:
        record(
            "contract",
            ReviewOutcome.FAIL,
            code="QA_CONTRACT_INVALID",
            message="Subject contract is invalid or incomplete",
        )
    else:
        record("contract", ReviewOutcome.PASS)

    expected_revision = criteria.get("expected_revision")
    if expected_revision is not None and subject.get("revision") != expected_revision:
        record(
            "subject-version",
            ReviewOutcome.NEEDS_REVIEW,
            code="QA_STALE_SUBJECT",
            message="Subject revision does not match the review criteria",
        )
    else:
        record("subject-version", ReviewOutcome.PASS)

    expected_context_revision = context.get("expected_product_context_revision")
    actual_context_revision = context.get("product_context_revision")
    if expected_context_revision is not None and actual_context_revision != expected_context_revision:
        record(
            "product-context-version",
            ReviewOutcome.NEEDS_REVIEW,
            code="QA_STALE_PRODUCT_CONTEXT",
            message="Product context revision is stale",
        )
    else:
        record("product-context-version", ReviewOutcome.PASS)

    required_roles = tuple(str(item) for item in criteria.get("required_asset_roles", ()))
    assets = subject.get("assets", ())
    role_approval = {
        str(item.get("role")): item.get("approved") is True
        for item in assets
        if isinstance(item, Mapping)
    }
    if any(not role_approval.get(role, False) for role in required_roles):
        record(
            "asset-identity-and-approval",
            ReviewOutcome.FAIL,
            code="QA_ASSET_REQUIRED_OR_UNAPPROVED",
            message="A required asset role is missing or unapproved",
        )
    else:
        record("asset-identity-and-approval", ReviewOutcome.PASS)

    product_mismatch = any(
        criteria.get(expected_key) is not None
        and subject.get(actual_key) != criteria.get(expected_key)
        for expected_key, actual_key in (
            ("expected_product_id", "product_id"),
            ("expected_sku_id", "sku_id"),
        )
    )
    if product_mismatch:
        record(
            "product-identity",
            ReviewOutcome.FAIL,
            code="QA_PRODUCT_IDENTITY_MISMATCH",
            message="Product or SKU identity does not match the review criteria",
        )
    else:
        record("product-identity", ReviewOutcome.PASS)

    expected_continuity = criteria.get("continuity", {})
    actual_continuity = subject.get("continuity", {})
    continuity_mismatch = any(
        actual_continuity.get(key) != expected
        for key, expected in expected_continuity.items()
    ) if isinstance(expected_continuity, Mapping) and isinstance(actual_continuity, Mapping) else True
    if continuity_mismatch:
        record(
            "continuity",
            ReviewOutcome.FAIL,
            code="QA_CONTINUITY_DRIFT",
            message="Continuity anchors do not match",
        )
    else:
        record("continuity", ReviewOutcome.PASS)

    max_drift = criteria.get("max_drift", {})
    actual_drift = subject.get("drift", {})
    drift_missing = False
    drift_exceeded = False
    if isinstance(max_drift, Mapping) and isinstance(actual_drift, Mapping):
        for metric, maximum in max_drift.items():
            actual = actual_drift.get(metric)
            if not isinstance(actual, (int, float)):
                drift_missing = True
            elif actual > maximum:
                drift_exceeded = True
    elif max_drift:
        drift_missing = True
    if drift_exceeded:
        record("drift", ReviewOutcome.FAIL, code="QA_DRIFT_LIMIT_EXCEEDED", message="Drift budget exceeded")
    elif drift_missing:
        record("drift", ReviewOutcome.NEEDS_REVIEW, code="QA_DRIFT_EVIDENCE_MISSING", message="Drift evidence is missing")
    else:
        record("drift", ReviewOutcome.PASS)

    quality_rules = criteria.get("quality", {})
    quality_values = subject.get("quality", {})
    quality_missing = False
    quality_failed = False
    if isinstance(quality_rules, Mapping) and isinstance(quality_values, Mapping):
        for metric, limits in quality_rules.items():
            actual = quality_values.get(metric)
            if not isinstance(actual, (int, float)) or not isinstance(limits, Mapping):
                quality_missing = True
                continue
            if "min" in limits and actual < limits["min"]:
                quality_failed = True
            if "max" in limits and actual > limits["max"]:
                quality_failed = True
    elif quality_rules:
        quality_missing = True
    if quality_failed:
        record("quality", ReviewOutcome.FAIL, code="QA_QUALITY_THRESHOLD_FAILED", message="Quality threshold failed")
    elif quality_missing:
        record("quality", ReviewOutcome.NEEDS_REVIEW, code="QA_QUALITY_EVIDENCE_MISSING", message="Quality evidence is missing")
    else:
        record("quality", ReviewOutcome.PASS)

    if subject.get("partial_failure") is True:
        record("partial-failure", ReviewOutcome.NEEDS_REVIEW, code="QA_PARTIAL_FAILURE", message="Upstream output is partial")

    return _build_artifacts(request, results, issues)


def _build_artifacts(
    request: ReviewRequest,
    results: list[dict[str, Any]],
    issues: list[dict[str, str]],
) -> ReviewArtifacts:
    subject = request.subject
    criteria = request.criteria
    context = request.context
    issue_outcomes = {item["outcome"] for item in issues}
    if ReviewOutcome.FAIL.value in issue_outcomes:
        outcome = ReviewOutcome.FAIL
    elif ReviewOutcome.NEEDS_REVIEW.value in issue_outcomes:
        outcome = ReviewOutcome.NEEDS_REVIEW
    else:
        outcome = ReviewOutcome.PASS

    subject_ref = {
        "artifact_id": str(subject.get("artifact_id", "unknown")),
        "artifact_type": str(subject.get("artifact_type", "unknown")),
        "revision": subject.get("revision"),
    }
    decision = {
        ReviewOutcome.PASS: "approve",
        ReviewOutcome.FAIL: "reject",
        ReviewOutcome.NEEDS_REVIEW: "defer",
    }[outcome]
    review_decision = {
        "review_decision_id": f"review-{request.execution_id}",
        "subject_ref": subject_ref,
        "decision": decision,
        "decided_by": f"skill:{SKILL_ID}@{SKILL_VERSION}",
        "decided_at": EVALUATED_AT,
        "criteria_results": results,
        "evidence_refs": list(request.evidence_refs),
    }
    validate_payload(
        "avp.contract.review-decision", review_decision,
        producer_component_id=SKILL_ID, producer_agent="skill",
    )

    feedback_events: list[dict[str, Any]] = []
    if outcome is ReviewOutcome.FAIL:
        product_id = criteria.get("expected_product_id") or subject.get("product_id")
        scope = "product" if product_id else "skill"
        scope_key = {"product_id": product_id} if product_id else {"skill_id": SKILL_ID}
        feedback = {
            "feedback_id": f"feedback-{request.execution_id}",
            "task_id": request.task_id,
            "source_skill_id": SKILL_ID,
            "feedback_type": "qa_failure",
            "statement": "QA review found one or more failing criteria",
            "evidence_refs": list(request.evidence_refs),
            "rule_scope": scope,
            "scope_key": scope_key,
            "bindings": {},
            "observed_at": EVALUATED_AT,
            "submitted_by": f"skill:{SKILL_ID}",
            "severity": "high",
        }
        if product_id:
            feedback["product_id"] = product_id
        validate_payload(
            "avp.contract.feedback-event", feedback,
            producer_component_id=SKILL_ID, producer_agent="skill",
        )
        feedback_events.append(feedback)

    output_refs = [review_decision["review_decision_id"], *[item["feedback_id"] for item in feedback_events]]
    event = {
        "execution_id": request.execution_id,
        "task_id": request.task_id,
        "skill_id": SKILL_ID,
        "event_type": "completed",
        "sequence": 1,
        "occurred_at": EVALUATED_AT,
        "status": "completed",
        "input_contract_refs": list(request.evidence_refs),
        "output_contract_refs": output_refs,
        "metrics": {"outcome": outcome.value, "criteria_count": len(results), "issue_count": len(issues)},
    }
    recovery_from = context.get("recovery_from_execution_id")
    if recovery_from:
        event["retry_of_execution_id"] = recovery_from
    validate_payload(
        "avp.contract.skill-execution-event", event,
        producer_component_id=SKILL_ID, producer_agent="skill",
    )
    package = {
        "schema_version": "1.0.0",
        "skill_version": SKILL_VERSION,
        "criteria_version": request.criteria_version,
        "evaluation_set_version": request.evaluation_set_version,
        "subject_ref": subject_ref,
        "outcome": outcome.value,
        "criteria_results": results,
        "issues": issues,
        "evidence_refs": list(request.evidence_refs),
        "operator_actions": ["inspect-evidence", "record-human-decision"] if outcome is ReviewOutcome.NEEDS_REVIEW else [],
    }
    findings = []
    for issue in issues:
        findings.append(
            {
                "error_code": issue.get("code"),
                "severity": issue.get("severity", "error"),
                "artifact_id": issue.get("artifact_id", issue.get("offending_artifact")),
                "field_paths": list(issue.get("field_paths", ())),
                "message": issue.get("message"),
            }
        )
    evaluation_inputs = context.get("evaluation_inputs", context.get("input_revisions", {}))
    if not isinstance(evaluation_inputs, Mapping):
        evaluation_inputs = {}
    readiness = "READY" if outcome is ReviewOutcome.PASS else ("REVOKED" if context.get("withdrawal_authorized") is True else "INVALIDATED")
    package["qa_report"] = {
        "artifact_type": "StoryboardArtifactChainQAReport",
        "schema_version": request.schema_version,
        "decision": outcome.value.upper(),
        "findings": findings,
        "evaluation_set": {
            "task_id": request.task_id,
            "execution_id": request.execution_id,
            "schema_version": request.schema_version,
            "criteria_version": request.criteria_version,
            "evaluation_set_version": request.evaluation_set_version,
            "input_revisions_digests": dict(evaluation_inputs),
        },
        "ruleset_version": request.criteria_version,
        "qa_code_commit": str(context.get("qa_code_commit", "workspace")),
        "execution_environment": {
            "python": str(context.get("python_version", "3.14")),
            "platform": os.name,
        },
        "readiness": readiness,
        "execution_artifacts_suppressed": outcome is not ReviewOutcome.PASS,
        "provider_execution_input": False,
        "owner_artifacts_mutated": False,
    }
    return ReviewArtifacts(
        outcome=outcome,
        review_decision=_freeze(review_decision),
        feedback_events=tuple(_freeze(item) for item in feedback_events),
        human_review_package=_freeze(package),
        skill_execution_event=_freeze(event),
    )
