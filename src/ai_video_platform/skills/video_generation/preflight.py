"""Validate approval, budget, binding, and package before any Provider seam."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import re
from typing import Any

from .errors import GenerationError, GenerationErrorCode
from .models import CONTRACT_STATUS, SCHEMA_VERSION, content_digest, parse_utc, snapshot


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CREDENTIAL_REFERENCE = re.compile(r"^(?:secret|env)://[A-Za-z0-9._/-]+$")
_SENSITIVE_INPUT_KEY = re.compile(r"(?i)(authorization|credential|api[_-]?key|token|secret|password|private[_-]?key)")


def contains_sensitive_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_SENSITIVE_INPUT_KEY.search(str(key)) or contains_sensitive_key(nested) for key, nested in value.items())
    if isinstance(value, list):
        return any(contains_sensitive_key(item) for item in value)
    return False


def require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, f"{field} must be an object", field_paths=(field,))
    try:
        return snapshot(value)
    except (TypeError, ValueError) as exc:
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, f"{field} must contain finite JSON values", field_paths=(field,)) from exc


def require_string(mapping: Mapping[str, object], field: str, code: GenerationErrorCode) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise GenerationError(code, f"{field} is required", field_paths=(field,))
    return value


class GenerationPreflight:
    """Pure preflight; successful inspection still performs no Provider action."""

    def inspect(self, request: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
        value = require_mapping(request, "request")
        evaluated_at = now or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            raise GenerationError(GenerationErrorCode.INVALID_INPUT, "now must be timezone-aware")
        package = self._package(value.get("execution_package"))
        approval = self._approval(value.get("approval_record"), package["package_digest"], evaluated_at)
        budget = self._budget(value.get("budget"))
        safe_binding = self._binding(value.get("provider_binding"))
        output = require_mapping(value.get("output"), "output")
        if not output:
            raise GenerationError(GenerationErrorCode.INVALID_INPUT, "output must not be empty", field_paths=("output",))
        if contains_sensitive_key(output):
            raise GenerationError(GenerationErrorCode.INVALID_INPUT, "output configuration contains a forbidden sensitive field", field_paths=("output",))
        idempotency_key = require_string(value, "idempotency_key", GenerationErrorCode.IDEMPOTENCY_KEY_REQUIRED)
        request_basis = {
            "package_digest": package["package_digest"],
            "approval_id": approval["approval_id"],
            "provider_binding": safe_binding,
            "budget": budget,
            "output": output,
        }
        return snapshot({
            "status": "ready",
            "schema_version": SCHEMA_VERSION,
            "contract_status": CONTRACT_STATUS,
            "request_hash": content_digest(request_basis),
            "idempotency_key": idempotency_key,
            "package_id": package["package_id"],
            "package_digest": package["package_digest"],
            "approval_id": approval["approval_id"],
            "provider_binding": safe_binding,
            "budget": budget,
            "output": output,
            "provider_execution_performed": False,
        })

    def _package(self, raw: object) -> dict[str, Any]:
        package = require_mapping(raw, "execution_package")
        if package.get("artifact_name") != "VideoExecutionPackage" or package.get("contract_status") != CONTRACT_STATUS:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Execution package identity/status is invalid")
        if package.get("schema_version") != SCHEMA_VERSION:
            raise GenerationError(GenerationErrorCode.PACKAGE_VERSION_UNSUPPORTED, "Execution package version is unsupported")
        if package.get("planning_provider_submission_performed") is not False:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Planning package cannot contain Provider submission")
        for field in ("package_id", "task_id"):
            require_string(package, field, GenerationErrorCode.PACKAGE_INVALID)
        for field in ("asset_mapping", "motion_plan"):
            if not isinstance(package.get(field), list) or not package[field]:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, f"Execution package {field} must be non-empty")
        master = require_mapping(package.get("storyboard_master"), "execution_package.storyboard_master")
        if master.get("planning_provider_submission_performed") is not False:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Nested planning artifact cannot contain Provider submission")
        if master.get("artifact_name") != "StoryboardMaster" or master.get("schema_version") != SCHEMA_VERSION or master.get("contract_status") != CONTRACT_STATUS:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Nested planning artifact identity/status is invalid")
        master_digest = master.get("master_digest")
        master_body = {key: item for key, item in master.items() if key != "master_digest"}
        if not isinstance(master_digest, str) or content_digest(master_body) != master_digest:
            raise GenerationError(GenerationErrorCode.PACKAGE_TAMPERED, "Nested planning artifact digest mismatch")
        if (
            package.get("asset_mapping") != master.get("asset_mapping")
            or package.get("visual_anchors") != master.get("visual_anchors")
            or package.get("motion_plan") != master.get("motion_plan")
        ):
            raise GenerationError(GenerationErrorCode.PACKAGE_TAMPERED, "Execution package disagrees with nested planning artifact")
        supplied = package.get("package_digest")
        if not isinstance(supplied, str) or _DIGEST.fullmatch(supplied) is None:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Execution package digest is invalid")
        body = {key: item for key, item in package.items() if key != "package_digest"}
        if content_digest(body) != supplied:
            raise GenerationError(GenerationErrorCode.PACKAGE_TAMPERED, "Execution package digest mismatch")
        return package

    def _approval(self, raw: object, package_digest: str, now: datetime) -> dict[str, Any]:
        if raw is None:
            raise GenerationError(GenerationErrorCode.APPROVAL_REQUIRED, "ApprovalRecord is required")
        approval = require_mapping(raw, "approval_record")
        approval_id = require_string(approval, "approval_id", GenerationErrorCode.APPROVAL_REQUIRED)
        if approval.get("approval_type") != "video_generation" or approval.get("outcome") != "approved":
            raise GenerationError(GenerationErrorCode.APPROVAL_NOT_EFFECTIVE, "ApprovalRecord is not effective for video generation")
        authority = require_mapping(approval.get("authority"), "approval_record.authority")
        if require_string(authority, "boundary_id", GenerationErrorCode.APPROVAL_NOT_EFFECTIVE) != "authorized-approval-boundary":
            raise GenerationError(GenerationErrorCode.APPROVAL_NOT_EFFECTIVE, "ApprovalRecord authority is not an authorized boundary")
        require_string(approval, "decision_ref", GenerationErrorCode.APPROVAL_NOT_EFFECTIVE)
        subject = require_mapping(approval.get("subject_ref"), "approval_record.subject_ref")
        if subject.get("digest") != package_digest:
            raise GenerationError(GenerationErrorCode.APPROVAL_SUBJECT_MISMATCH, "Approval subject does not match execution package")
        try:
            decided_at = parse_utc(approval.get("decided_at"), "approval_record.decided_at")
            valid_until = parse_utc(approval.get("valid_until"), "approval_record.valid_until")
        except (TypeError, ValueError) as exc:
            raise GenerationError(GenerationErrorCode.APPROVAL_NOT_EFFECTIVE, "Approval timestamps are invalid") from exc
        evaluated_at = now.astimezone(timezone.utc)
        if decided_at > evaluated_at or valid_until <= evaluated_at or decided_at >= valid_until:
            raise GenerationError(GenerationErrorCode.APPROVAL_NOT_EFFECTIVE, "ApprovalRecord is expired")
        return {"approval_id": approval_id}

    def _budget(self, raw: object) -> dict[str, object]:
        budget = require_mapping(raw, "budget")
        estimated = budget.get("estimated_cost_units")
        maximum = budget.get("max_cost_units")
        if isinstance(estimated, bool) or not isinstance(estimated, (int, float)) or estimated < 0:
            raise GenerationError(GenerationErrorCode.BUDGET_INVALID, "estimated_cost_units must be nonnegative")
        if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or maximum <= 0:
            raise GenerationError(GenerationErrorCode.BUDGET_INVALID, "max_cost_units must be positive")
        for field in ("max_requests", "max_concurrency", "max_attempts", "timeout_seconds"):
            value = budget.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise GenerationError(GenerationErrorCode.BUDGET_INVALID, f"{field} must be a positive integer")
        if estimated > maximum:
            raise GenerationError(GenerationErrorCode.BUDGET_EXCEEDED, "Estimated video cost exceeds approved budget")
        return snapshot(budget)

    def _binding(self, raw: object) -> dict[str, str]:
        binding = require_mapping(raw, "provider_binding")
        safe = {
            field: require_string(binding, field, GenerationErrorCode.PROVIDER_BINDING_INVALID)
            for field in ("binding_ref", "provider_id", "model_id")
        }
        credential_ref = binding.get("credential_ref")
        if not isinstance(credential_ref, str) or _CREDENTIAL_REFERENCE.fullmatch(credential_ref) is None:
            raise GenerationError(
                GenerationErrorCode.CREDENTIAL_REFERENCE_INVALID,
                "An approved opaque credential reference is required",
                field_paths=("provider_binding.credential_ref",),
            )
        return safe
