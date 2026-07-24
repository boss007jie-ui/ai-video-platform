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
        if package.get("schema_version") != SCHEMA_VERSION:
            raise GenerationError(GenerationErrorCode.PACKAGE_VERSION_UNSUPPORTED, "Execution package version is unsupported")
        self._artifact_identity(package, "VideoExecutionPackage", "avp.contract.video-execution-package")
        if package.get("planning_provider_submission_performed") is not False:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Planning package cannot contain Provider submission")
        package_id = require_string(package, "package_id", GenerationErrorCode.PACKAGE_INVALID)
        artifacts = {
            "video_generation_storyboard_master": ("VideoGenerationStoryboardMaster", "avp.contract.video-generation-storyboard-master"),
            "shot_motion_plan": ("ShotMotionPlan", "avp.contract.shot-motion-plan"),
            "first_frame_mapping": ("FirstFrameMapping", "avp.contract.first-frame-mapping"),
            "reference_role_mapping": ("ReferenceRoleMapping", "avp.contract.reference-role-mapping"),
        }
        nested: dict[str, dict[str, Any]] = {}
        revisions = {package.get("planning_revision")}
        for field, (name, contract_id) in artifacts.items():
            artifact = require_mapping(package.get(field), f"execution_package.{field}")
            self._artifact_identity(artifact, name, contract_id)
            revisions.add(artifact.get("planning_revision"))
            nested[field] = artifact
        if len(revisions) != 1 or not isinstance(package.get("planning_revision"), str) or not package["planning_revision"]:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Planning artifact revisions disagree")

        master = nested["video_generation_storyboard_master"]
        shots = master.get("shots")
        if not isinstance(shots, list) or not shots:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Storyboard master shots must be non-empty")
        target_ratio = master.get("target_aspect_ratio")
        if not isinstance(target_ratio, str) or not target_ratio.strip():
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Storyboard target aspect ratio is invalid")
        shot_order: list[str] = []
        panel_order: list[str] = []
        panel_by_shot: dict[str, tuple[str, str, str]] = {}
        required_shot_fields = {
            "shot_id", "sequence", "panel_id", "panel_asset_ref", "panel_sha256", "duration_ms",
            "start_state", "middle_state", "end_state", "motion_path", "character_state", "product_state",
            "emotion", "camera_motion", "transition", "voiceover", "caption", "sound_effect", "cta",
        }
        for index, raw_shot in enumerate(shots):
            shot = require_mapping(raw_shot, f"execution_package.video_generation_storyboard_master.shots[{index}]")
            if required_shot_fields - set(shot) or shot.get("sequence") != index + 1:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Storyboard master shot is incomplete or unordered")
            shot_id = require_string(shot, "shot_id", GenerationErrorCode.PACKAGE_INVALID)
            panel_id = require_string(shot, "panel_id", GenerationErrorCode.PACKAGE_INVALID)
            asset_ref = require_string(shot, "panel_asset_ref", GenerationErrorCode.PACKAGE_INVALID)
            digest = shot.get("panel_sha256")
            if shot_id in panel_by_shot or not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Storyboard panel binding is invalid")
            duration = shot.get("duration_ms")
            if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Storyboard shot duration is invalid")
            for field in required_shot_fields - {"shot_id", "sequence", "panel_id", "panel_asset_ref", "panel_sha256", "duration_ms"}:
                if not isinstance(shot.get(field), str) or (field != "cta" and not shot[field].strip()):
                    raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Storyboard shot state fields are invalid")
            shot_order.append(shot_id)
            panel_order.append(panel_id)
            panel_by_shot[shot_id] = (panel_id, asset_ref, digest)
        if package.get("shot_order") != shot_order or package.get("panel_order") != panel_order:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Execution package shot/panel order diverges")
        expected_package_id = "vep-" + content_digest({"revision": package["planning_revision"], "shots": shot_order}).removeprefix("sha256:")[:20]
        if package_id != expected_package_id or package.get("approved_panel_refs") != [panel_by_shot[shot][1] for shot in shot_order]:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Execution package identity or approved panel order is invalid")

        first = nested["first_frame_mapping"]
        forbidden_flags = ("contains_grid", "contains_number", "contains_label", "contains_caption", "contains_other_shot")
        first_ref = str(first.get("asset_ref", "")).lower()
        expected_first = panel_by_shot[shot_order[0]]
        if (
            first.get("shot_id") != shot_order[0] or first.get("panel_id") != expected_first[0]
            or first.get("asset_ref") != expected_first[1] or first.get("sha256") != expected_first[2]
            or first.get("asset_role") != "clean_full_frame_panel" or first.get("aspect_ratio") != target_ratio or first.get("clean_full_frame") is not True
            or any(first.get(flag) is not False for flag in forbidden_flags)
            or any(marker in first_ref for marker in ("analysis", "evidence", "replication", "contact_sheet", "contact-sheet"))
        ):
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "First frame is not the approved clean first production panel")

        role_map = nested["reference_role_mapping"]
        if master.get("first_frame_mapping_ref") != first.get("artifact_digest") or master.get("reference_role_mapping_ref") != role_map.get("artifact_digest"):
            raise GenerationError(GenerationErrorCode.PACKAGE_TAMPERED, "Storyboard master artifact references are stale")
        references = role_map.get("references")
        if not isinstance(references, list):
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Reference role mapping is invalid")
        provider_refs: dict[str, dict[str, Any]] = {}
        for index, raw_reference in enumerate(references):
            reference = require_mapping(raw_reference, f"execution_package.reference_role_mapping.references[{index}]")
            asset_ref = require_string(reference, "asset_ref", GenerationErrorCode.PACKAGE_INVALID)
            role = reference.get("role")
            structural = role == "global_structure_reference" or any(marker in asset_ref.lower() for marker in ("analysis", "evidence", "replication", "contact_sheet", "contact-sheet"))
            if structural:
                if role != "global_structure_reference" or reference.get("provider_execution_input") is not False or reference.get("first_frame_eligible") is not False:
                    raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Structural analysis references cannot be Provider inputs")
            else:
                if role not in {"character_reference", "product_reference", "style_reference"} or reference.get("provider_execution_input") is not True or reference.get("first_frame_eligible") is not False:
                    raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Provider reference role is invalid")
                if asset_ref in provider_refs:
                    raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Provider reference mapping is duplicated")
                provider_refs[asset_ref] = reference

        mappings = package.get("asset_mapping")
        if not isinstance(mappings, list):
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Execution package asset mapping is invalid")
        mapped_panels: dict[str, str] = {}
        mapped_refs: set[str] = set()
        for index, raw_mapping in enumerate(mappings):
            mapping = require_mapping(raw_mapping, f"execution_package.asset_mapping[{index}]")
            uri = require_string(mapping, "uri", GenerationErrorCode.PACKAGE_INVALID)
            sha = mapping.get("sha256")
            if mapping.get("approval_state") != "approved" or not isinstance(sha, str) or _DIGEST.fullmatch(sha) is None:
                raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Execution asset is not approved or has an invalid digest")
            if mapping.get("role") == "production_panel":
                shot_id = require_string(mapping, "shot_id", GenerationErrorCode.PACKAGE_INVALID)
                expected = panel_by_shot.get(shot_id)
                if shot_id in mapped_panels or expected is None or mapping.get("panel_id") != expected[0] or uri != expected[1] or sha != expected[2]:
                    raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Production panel mapping diverges from the storyboard master")
                mapped_panels[shot_id] = uri
            else:
                reference = provider_refs.get(uri)
                if uri in mapped_refs or reference is None or mapping.get("role") != reference.get("role") or mapping.get("provider_execution_input") is not True or sha != reference.get("sha256"):
                    raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Reference mapping is not approved for Provider execution")
                mapped_refs.add(uri)
        if list(mapped_panels) != shot_order or mapped_refs != set(provider_refs):
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Execution asset mapping is incomplete or unordered")

        motion = nested["shot_motion_plan"].get("shots")
        motion_fields = ("shot_id", "sequence", "duration_ms", "start_state", "middle_state", "end_state", "motion_path", "camera_motion", "transition")
        expected_motion = [{field: shot[field] for field in motion_fields} for shot in shots]
        if not isinstance(motion, list) or motion != expected_motion:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Shot motion plan does not cover the storyboard order")

        for artifact in (*nested.values(), package):
            self._artifact_digest(artifact)
        supplied = package.get("artifact_digest")
        if not isinstance(supplied, str) or _DIGEST.fullmatch(supplied) is None:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, "Execution package digest is invalid")
        return {**package, "package_digest": supplied}

    @staticmethod
    def _artifact_identity(artifact: Mapping[str, object], name: str, contract_id: str) -> None:
        if artifact.get("artifact_name") != name or artifact.get("contract_id") != contract_id or artifact.get("contract_status") != CONTRACT_STATUS:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, f"{name} identity/status is invalid")
        if artifact.get("schema_version") != SCHEMA_VERSION:
            raise GenerationError(GenerationErrorCode.PACKAGE_INVALID, f"{name} version is unsupported")

    @staticmethod
    def _artifact_digest(artifact: Mapping[str, object]) -> None:
        supplied = artifact.get("artifact_digest")
        body = {key: value for key, value in artifact.items() if key != "artifact_digest"}
        if not isinstance(supplied, str) or _DIGEST.fullmatch(supplied) is None or content_digest(body) != supplied:
            raise GenerationError(GenerationErrorCode.PACKAGE_TAMPERED, "Planning artifact digest mismatch")

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
