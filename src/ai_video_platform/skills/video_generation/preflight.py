"""Validate approval, budget, binding, and package before any Provider seam."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import re
from typing import Any

from .errors import GenerationError, GenerationErrorCode, contains_sensitive_text
from .models import CONTRACT_STATUS, SCHEMA_VERSION, content_digest, parse_utc, snapshot


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CREDENTIAL_REFERENCE = re.compile(r"^(?:secret|env)://[A-Za-z0-9._/-]+$")
_SENSITIVE_INPUT_KEY = re.compile(r"(?i)(authorization|credential|api[_-]?key|token|secret|password|private[_-]?key)")


def contains_sensitive_material(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            _SENSITIVE_INPUT_KEY.search(str(key))
            or contains_sensitive_material(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(contains_sensitive_material(item) for item in value)
    if isinstance(value, str):
        return contains_sensitive_text(value)
    return False


def require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, f"{field} must be an object", field_paths=(field,))
    try:
        return snapshot(value)
    except (TypeError, ValueError):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, f"{field} must contain finite JSON values", field_paths=(field,)) from None


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
        if contains_sensitive_material(output):
            raise GenerationError(GenerationErrorCode.INVALID_INPUT, "output configuration contains a forbidden sensitive field", field_paths=("output",))
        idempotency_key = require_string(value, "idempotency_key", GenerationErrorCode.IDEMPOTENCY_KEY_REQUIRED)
        request_basis = {
            "package_digest": package["package_digest"],
            "approval_id": approval["approval_id"],
            "provider_binding": safe_binding,
            "credential_ref_digest": content_digest(require_mapping(value.get("provider_binding"), "provider_binding")["credential_ref"]),
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
        package_id = require_string(package, "package_id", GenerationErrorCode.PACKAGE_INVALID)
        task_id = require_string(package, "task_id", GenerationErrorCode.PACKAGE_INVALID)
        source = self._source(package.get("source"), "execution_package.source")
        expected_package_id = "vep-" + content_digest(source).removeprefix("sha256:")[:20]
        if package_id != expected_package_id:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Execution package identifier is invalid")
        master = require_mapping(package.get("storyboard_master"), "execution_package.storyboard_master")
        if master.get("planning_provider_submission_performed") is not False:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Nested planning artifact cannot contain Provider submission")
        if master.get("artifact_name") != "StoryboardMaster" or master.get("schema_version") != SCHEMA_VERSION or master.get("contract_status") != CONTRACT_STATUS:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Nested planning artifact identity/status is invalid")
        master_task_id = require_string(master, "task_id", GenerationErrorCode.PACKAGE_INVALID)
        master_source = self._source(master.get("source"), "execution_package.storyboard_master.source")
        master_digest = master.get("master_digest")
        master_body = {key: item for key, item in master.items() if key != "master_digest"}
        if not isinstance(master_digest, str) or content_digest(master_body) != master_digest:
            raise GenerationError(GenerationErrorCode.PACKAGE_TAMPERED, "Nested planning artifact digest mismatch")
        if master_task_id != task_id or master_source != source:
            raise GenerationError(GenerationErrorCode.PACKAGE_TAMPERED, "Execution package task or source disagrees with nested planning artifact")
        self._planning_payload(master)
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

    def _source(self, raw: object, field: str) -> dict[str, Any]:
        source = require_mapping(raw, field)
        for name in ("storyboard_id", "asset_manifest_id"):
            require_string(source, name, GenerationErrorCode.PACKAGE_INVALID)
        for name in ("storyboard_revision", "asset_manifest_revision"):
            value = source.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, f"{field}.{name} must be a positive integer")
        for name in ("storyboard_digest", "asset_manifest_digest"):
            value = source.get(name)
            if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, f"{field}.{name} must be a sha256 digest")
        return source

    def _planning_payload(self, master: Mapping[str, object]) -> None:
        shots = master.get("shots")
        mappings = master.get("asset_mapping")
        anchors = master.get("visual_anchors")
        motions = master.get("motion_plan")
        if not isinstance(shots, list) or not shots:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Nested planning artifact shots must be non-empty")
        if not isinstance(mappings, list) or not mappings:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Nested planning artifact asset_mapping must be non-empty")
        if not isinstance(anchors, list) or not anchors:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Nested planning artifact visual_anchors must be non-empty")
        if not isinstance(motions, list) or not motions:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Nested planning artifact motion_plan must be non-empty")

        required_pairs: set[tuple[str, str]] = set()
        shot_ids: set[str] = set()
        sequences: set[int] = set()
        shot_sequences: dict[str, int] = {}
        shot_motions: dict[str, object] = {}
        shot_anchors: dict[str, object] = {}
        continuity_groups: set[str] = set()
        for index, raw_shot in enumerate(shots):
            shot = require_mapping(raw_shot, f"shots[{index}]")
            shot_id = require_string(shot, "shot_id", GenerationErrorCode.PACKAGE_INVALID)
            sequence = shot.get("sequence")
            roles = shot.get("required_asset_roles")
            continuity = require_string(shot, "continuity_group", GenerationErrorCode.PACKAGE_INVALID)
            if shot_id in shot_ids or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0 or sequence in sequences:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Shot identifiers and positive sequences must be unique")
            if not isinstance(roles, list) or not roles or any(not isinstance(role, str) or not role.strip() for role in roles):
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Each shot requires non-empty asset roles")
            if len(set(roles)) != len(roles) or not isinstance(shot.get("visual_anchor"), Mapping) or not isinstance(shot.get("motion"), Mapping):
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Shot planning fields are invalid")
            if continuity in shot_anchors and shot_anchors[continuity] != shot["visual_anchor"]:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Shots in one continuity group disagree on their visual anchor")
            shot_ids.add(shot_id)
            sequences.add(sequence)
            shot_sequences[shot_id] = sequence
            shot_motions[shot_id] = shot["motion"]
            shot_anchors[continuity] = shot["visual_anchor"]
            continuity_groups.add(continuity)
            required_pairs.update((shot_id, role) for role in roles)

        mapped_pairs: set[tuple[str, str]] = set()
        for index, raw_mapping in enumerate(mappings):
            mapping = require_mapping(raw_mapping, f"asset_mapping[{index}]")
            pair = (
                require_string(mapping, "shot_id", GenerationErrorCode.PACKAGE_INVALID),
                require_string(mapping, "role", GenerationErrorCode.PACKAGE_INVALID),
            )
            require_string(mapping, "asset_id", GenerationErrorCode.PACKAGE_INVALID)
            require_string(mapping, "uri", GenerationErrorCode.PACKAGE_INVALID)
            sha = mapping.get("sha256")
            if pair in mapped_pairs or not isinstance(sha, str) or _DIGEST.fullmatch(sha) is None:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Asset mapping is duplicated or has an invalid digest")
            mapped_pairs.add(pair)
        if mapped_pairs != required_pairs:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Asset mapping does not exactly cover required shot roles")

        anchor_groups: set[str] = set()
        for index, raw_anchor in enumerate(anchors):
            anchor = require_mapping(raw_anchor, f"visual_anchors[{index}]")
            group = require_string(anchor, "continuity_group", GenerationErrorCode.PACKAGE_INVALID)
            if group in anchor_groups or not isinstance(anchor.get("anchor"), Mapping) or anchor.get("anchor") != shot_anchors.get(group):
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Visual anchor is duplicated or invalid")
            anchor_groups.add(group)
        if anchor_groups != continuity_groups:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Visual anchors do not exactly cover continuity groups")

        motion_ids: set[str] = set()
        for index, raw_motion in enumerate(motions):
            motion = require_mapping(raw_motion, f"motion_plan[{index}]")
            shot_id = require_string(motion, "shot_id", GenerationErrorCode.PACKAGE_INVALID)
            sequence = motion.get("sequence")
            if shot_id in motion_ids or shot_id not in shot_ids or sequence != shot_sequences.get(shot_id) or not isinstance(motion.get("motion"), Mapping) or motion.get("motion") != shot_motions.get(shot_id):
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Motion plan is duplicated or invalid")
            motion_ids.add(shot_id)
        if motion_ids != shot_ids:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Motion plan does not exactly cover shots")

    def _approval(self, raw: object, package_digest: str, now: datetime) -> dict[str, Any]:
        if raw is None:
            raise GenerationError(GenerationErrorCode.APPROVAL_REQUIRED, "ApprovalRecord is required")
        approval = require_mapping(raw, "approval_record")
        approval_id = require_string(approval, "approval_id", GenerationErrorCode.APPROVAL_REQUIRED)
        if approval.get("approval_type") != "video_generation" or approval.get("outcome") != "approved":
            raise GenerationError(GenerationErrorCode.APPROVAL_NOT_EFFECTIVE, "ApprovalRecord is not effective for video generation")
        authority = require_mapping(approval.get("authority"), "approval_record.authority")
        authority_id = authority.get("authority_id", authority.get("boundary_id"))
        if authority_id != "authorized-approval-boundary":
            raise GenerationError(GenerationErrorCode.APPROVAL_NOT_EFFECTIVE, "ApprovalRecord authority is not an authorized boundary")
        require_string(approval, "decision_ref", GenerationErrorCode.APPROVAL_NOT_EFFECTIVE)
        subject = require_mapping(approval.get("subject_ref"), "approval_record.subject_ref")
        if subject.get("digest") != package_digest:
            raise GenerationError(GenerationErrorCode.APPROVAL_SUBJECT_MISMATCH, "Approval subject does not match execution package")
        try:
            decided_at = parse_utc(approval.get("decided_at"), "approval_record.decided_at")
            valid_until = parse_utc(approval["valid_until"], "approval_record.valid_until") if approval.get("valid_until") is not None else None
        except (TypeError, ValueError):
            raise GenerationError(GenerationErrorCode.APPROVAL_NOT_EFFECTIVE, "Approval timestamps are invalid") from None
        evaluated_at = now.astimezone(timezone.utc)
        if decided_at > evaluated_at or (valid_until is not None and (valid_until <= evaluated_at or decided_at >= valid_until)):
            raise GenerationError(GenerationErrorCode.APPROVAL_NOT_EFFECTIVE, "ApprovalRecord is expired")
        return {"approval_id": approval_id}

    def _budget(self, raw: object) -> dict[str, object]:
        budget = require_mapping(raw, "budget")
        allowed = {
            "estimated_cost_units", "max_cost_units", "max_requests",
            "max_concurrency", "max_attempts", "timeout_seconds",
        }
        if set(budget) != allowed or contains_sensitive_material(budget):
            raise GenerationError(GenerationErrorCode.BUDGET_INVALID, "Budget contains missing, unknown, or sensitive fields")
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
        return {field: budget[field] for field in sorted(allowed)}

    def _binding(self, raw: object) -> dict[str, str]:
        binding = require_mapping(raw, "provider_binding")
        allowed = {"binding_ref", "provider_id", "model_id", "credential_ref"}
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
        if set(binding) != allowed or contains_sensitive_material({key: value for key, value in binding.items() if key != "credential_ref"}):
            raise GenerationError(GenerationErrorCode.PROVIDER_BINDING_INVALID, "Provider binding contains missing, unknown, or sensitive fields")
        return safe
