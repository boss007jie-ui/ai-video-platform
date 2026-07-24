"""Canonical, deterministic Video Planning artifact builder with no Provider seam."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .errors import PlanningError, PlanningErrorCode
from .models import CONTRACT_STATUS, SCHEMA_VERSION, content_digest, snapshot


CONTRACT_IDS = {
    "VideoGenerationStoryboardMaster": "avp.contract.video-generation-storyboard-master",
    "ShotMotionPlan": "avp.contract.shot-motion-plan",
    "VideoExecutionPackage": "avp.contract.video-execution-package",
    "FirstFrameMapping": "avp.contract.first-frame-mapping",
    "ReferenceRoleMapping": "avp.contract.reference-role-mapping",
}
FORBIDDEN_FIRST_FRAME_MARKERS = ("analysis", "evidence", "replication", "contact_sheet", "contact-sheet")
SHEET_EXECUTION_POLICY = {
    "role": "human_review_only",
    "first_frame_eligible": False,
    "provider_execution_input": False,
    "semantic_authority": False,
    "ocr_semantic_writeback": False,
}


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{field} must be an object", field_paths=(field,))
    try:
        return snapshot(value)
    except (TypeError, ValueError) as exc:
        raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{field} must contain finite JSON values", field_paths=(field,)) from exc


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{field} must be an array", field_paths=(field,))
    return list(value)


def _string(value: Mapping[str, object], field: str, prefix: str) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate.strip():
        raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{prefix}.{field} is required", field_paths=(f"{prefix}.{field}",))
    return candidate


def _artifact(name: str, revision: str, body: Mapping[str, object]) -> dict[str, object]:
    value = {
        "artifact_name": name,
        "contract_id": CONTRACT_IDS[name],
        "schema_version": SCHEMA_VERSION,
        "contract_status": CONTRACT_STATUS,
        "planning_revision": revision,
        **snapshot(body),
    }
    return snapshot({**value, "artifact_digest": content_digest(value)})


class VideoPlanningInterface:
    """Build the five registered planning payloads from approved production panels."""

    def build_storyboard_master(self, request: Mapping[str, object]) -> dict[str, object]:
        value = _mapping(request, "request")
        plan = _mapping(value.get("production_storyboard_plan"), "production_storyboard_plan")
        panels = _mapping(value.get("production_storyboard_panel_set"), "production_storyboard_panel_set")
        product = _mapping(value.get("product_context_bundle"), "product_context_bundle")
        self._identity(plan, "ProductionStoryboardPlan", "avp.contract.production-storyboard-plan")
        self._identity(panels, "ProductionStoryboardPanelSet", "avp.contract.production-storyboard-panel-set")
        revision_value = plan.get("planning_revision", plan.get("plan_revision", 1))
        revision = str(revision_value)
        product_id = _string(plan, "product_id", "production_storyboard_plan")
        target_ratio = str(plan.get("target_aspect_ratio", plan.get("aspect_ratio", ""))).strip()
        if not target_ratio:
            raise PlanningError(PlanningErrorCode.INVALID_INPUT, "production_storyboard_plan.target_aspect_ratio is required")
        panel_revision = panels.get("planning_revision", panels.get("panel_plan", {}).get("plan_revision") if isinstance(panels.get("panel_plan"), Mapping) else revision_value)
        if str(panel_revision) != revision or panels.get("product_id") != product_id or product.get("product_id") != product_id:
            raise PlanningError(PlanningErrorCode.STALE_INPUT_VERSION, "Planning revision or product identity diverges")

        approved_results = {
            item.get("panel_id") for item in (_mapping(raw, "approved_panel_results") for raw in _list(value.get("approved_panel_results"), "approved_panel_results"))
            if item.get("approval_state") == "approved"
        }
        panel_by_shot: dict[str, list[dict[str, Any]]] = {}
        panel_ids: set[str] = set()
        asset_ids: set[str] = set()
        for raw in _list(panels.get("panels"), "production_storyboard_panel_set.panels"):
            panel = _mapping(raw, "production_storyboard_panel_set.panels")
            panel_id = _string(panel, "panel_id", "panel")
            shot_id = _string(panel, "shot_id", "panel")
            facts = _mapping(panel.get("panel_asset_facts", {}), "panel.panel_asset_facts")
            binding = _mapping(panel.get("plan_binding_summary", {}), "panel.plan_binding_summary")
            usage_status = panel.get("usage_status", "SELECTED")
            approval_state = panel.get("approval_state", facts.get("approval_status"))
            qa_status = panel.get("qa_status", facts.get("qa_status"))
            approved_by_result = not approved_results or panel_id in approved_results
            if usage_status != "SELECTED" or approval_state not in {"approved", "APPROVED"} or qa_status not in {None, "pass", "PASS"} or not approved_by_result:
                raise PlanningError(PlanningErrorCode.ASSET_NOT_APPROVED, "Every execution panel must be approved")
            asset = _mapping(panel.get("asset", {}), "panel.asset")
            asset_id = panel.get("panel_asset_id", facts.get("panel_asset_id", asset.get("asset_id", panel.get("asset_ref"))))
            asset_ref = panel.get("asset_ref", asset.get("relative_path", asset_id))
            aspect_ratio = panel.get("aspect_ratio", facts.get("aspect_ratio"))
            digest = panel.get("sha256", facts.get("sha256", asset.get("sha256")))
            if not isinstance(asset_id, str) or not asset_id or not isinstance(asset_ref, str) or not asset_ref or not isinstance(aspect_ratio, str):
                raise PlanningError(PlanningErrorCode.INVALID_INPUT, "Panel asset facts are incomplete")
            normalized_digest = digest.removeprefix("sha256:") if isinstance(digest, str) else ""
            if re.fullmatch(r"[0-9a-f]{64}", normalized_digest) is None:
                raise PlanningError(PlanningErrorCode.INVALID_INPUT, "Panel digest is invalid")
            if panel_id in panel_ids or asset_id in asset_ids:
                raise PlanningError(PlanningErrorCode.ASSET_MAPPING_AMBIGUOUS, "Panel and asset bindings must be unique")
            if isinstance(panel.get("sequence"), bool) or not isinstance(panel.get("sequence"), int) or panel["sequence"] < 1:
                raise PlanningError(PlanningErrorCode.INVALID_SHOT_ORDER, "Panel sequence must be a positive integer")
            for flag in ("clean_full_frame", "contains_grid", "contains_number", "contains_label", "contains_caption", "contains_other_shot"):
                if flag in panel and not isinstance(panel.get(flag), bool):
                    raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"panel.{flag} must be boolean")
            panel.update(
                {
                    "panel_asset_id": asset_id,
                    "asset_ref": asset_ref,
                    "aspect_ratio": aspect_ratio,
                    "sha256": "sha256:" + normalized_digest,
                    "approval_ref": panel.get("approval_ref", panel.get("approval_evidence", {}).get("record_contract_id") if isinstance(panel.get("approval_evidence"), Mapping) else None),
                    "legacy_global_sequence": panel.get("panel_sequence") is None and binding.get("panel_sequence") is None,
                    "panel_sequence": panel.get("panel_sequence", binding.get("panel_sequence", 1)),
                    "timing_mode": panel.get("timing_mode", binding.get("timing_mode", "TEMPORAL_SEGMENT")),
                    "first_frame_role": panel.get("first_frame_role", binding.get("first_frame_role")),
                    "provider_reference_role": panel.get("provider_reference_role", binding.get("provider_reference_role")),
                    "semantic_provenance": binding.get("semantic_provenance", panel.get("semantic_provenance", {})),
                }
            )
            panel_ids.add(panel_id)
            asset_ids.add(asset_id)
            panel_by_shot.setdefault(shot_id, []).append(panel)

        ordered_shots: list[dict[str, object]] = []
        master_panel_entries: list[dict[str, object]] = []
        shot_order: list[str] = []
        panel_order: list[str] = []
        sequences: set[int] = set()
        required = ("duration_ms", "start_state", "middle_state", "end_state", "motion_path", "character_state", "product_state", "emotion", "camera_motion", "transition", "voiceover", "caption", "sound_effect", "cta")
        raw_shots = [_mapping(raw, "production_storyboard_plan.shots") for raw in _list(plan.get("shots"), "production_storyboard_plan.shots")]
        identities = [(shot.get("shot_id"), shot.get("sequence")) for shot in raw_shots]
        if (
            not identities
            or any(not isinstance(shot_id, str) or not shot_id or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1 for shot_id, sequence in identities)
            or len({shot_id for shot_id, _ in identities}) != len(identities)
            or {sequence for _, sequence in identities} != set(range(1, len(identities) + 1))
        ):
            raise PlanningError(PlanningErrorCode.INVALID_SHOT_ORDER, "Shots must have unique identities and one contiguous positive sequence")
        for shot in sorted(raw_shots, key=lambda item: item["sequence"]):
            shot_id = _string(shot, "shot_id", "shot")
            sequence = shot.get("sequence")
            if shot_id in shot_order or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1 or sequence in sequences:
                raise PlanningError(PlanningErrorCode.INVALID_SHOT_ORDER, "Shot identities and positive sequences must be unique")
            sequences.add(sequence)
            shot_panels = panel_by_shot.get(shot_id)
            if not shot_panels:
                raise PlanningError(PlanningErrorCode.ASSET_MAPPING_MISSING, "Every shot requires at least one approved panel")
            shot_panels = sorted(shot_panels, key=lambda item: item["panel_sequence"])
            if [panel["panel_sequence"] for panel in shot_panels] != list(range(1, len(shot_panels) + 1)):
                raise PlanningError(PlanningErrorCode.INVALID_SHOT_ORDER, "Panel sequence must be contiguous within its Shot")
            if len(shot_panels) == 1 and shot_panels[0]["legacy_global_sequence"] and shot_panels[0]["sequence"] != shot["sequence"]:
                raise PlanningError(PlanningErrorCode.STALE_INPUT_VERSION, "Legacy Panel and Shot order diverge")
            for field in required:
                if field not in shot:
                    raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"shot.{field} is required")
                if field == "duration_ms":
                    if isinstance(shot[field], bool) or not isinstance(shot[field], int) or shot[field] <= 0:
                        raise PlanningError(PlanningErrorCode.INVALID_INPUT, "shot.duration_ms must be a positive integer")
                elif not isinstance(shot[field], str) or (field != "cta" and not shot[field].strip()):
                    raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"shot.{field} must be text")
            panel_entries = []
            for panel in shot_panels:
                entry = {
                    "beat_id": panel.get("beat_id", shot.get("beat_id")),
                    "shot_id": shot_id,
                    "panel_id": panel["panel_id"],
                    "panel_asset_id": panel["panel_asset_id"],
                    "asset_ref": panel["asset_ref"],
                    "sha256": panel["sha256"],
                    "aspect_ratio": panel["aspect_ratio"],
                    "approval_status": "APPROVED",
                    "qa_status": "PASS",
                    "usage_status": "SELECTED",
                    "timing_mode": panel["timing_mode"],
                    "camera_motion": shot.get("camera_motion"),
                    "subject_motion": shot.get("subject_motion", shot.get("motion_path")),
                    "conversion_function": shot.get("conversion_function", shot.get("cta")),
                    "semantic_provenance": panel["semantic_provenance"],
                    "first_frame_role": panel.get("first_frame_role"),
                    "provider_reference_role": panel.get("provider_reference_role"),
                }
                timing = panel.get("timing_projection", {}) if isinstance(panel.get("timing_projection"), Mapping) else {}
                for timing_field in ("start_ms", "end_ms", "duration_ms", "anchor_time_ms", "anchor_role"):
                    if timing_field in panel:
                        entry[timing_field] = panel[timing_field]
                    elif timing_field in timing:
                        entry[timing_field] = timing[timing_field]
                if entry["timing_mode"] == "TEMPORAL_SEGMENT" and "duration_ms" not in entry:
                    entry.update({"start_ms": sum(item["duration_ms"] for item in ordered_shots), "end_ms": sum(item["duration_ms"] for item in ordered_shots) + shot["duration_ms"], "duration_ms": shot["duration_ms"]})
                panel_entries.append(snapshot(entry))
                master_panel_entries.append(snapshot(entry))
                panel_order.append(str(panel["panel_id"]))
            ordered_shots.append(
                snapshot(
                    {
                        **shot,
                        "panel_id": panel_entries[0]["panel_id"],
                        "panel_asset_ref": panel_entries[0]["asset_ref"],
                        "panel_sha256": panel_entries[0]["sha256"],
                        "master_panel_entries": panel_entries,
                    }
                )
            )
            shot_order.append(shot_id)
        if not shot_order or sequences != set(range(1, len(shot_order) + 1)):
            raise PlanningError(PlanningErrorCode.INVALID_SHOT_ORDER, "Shots must form one contiguous non-empty sequence")
        if set(panel_by_shot) != set(shot_order):
            raise PlanningError(PlanningErrorCode.STALE_INPUT_VERSION, "Panel set contains unknown or unordered shots")

        first_panel = sorted(panel_by_shot[shot_order[0]], key=lambda item: item["panel_sequence"])[0]
        self._validate_first_frame(first_panel, target_ratio)
        first_frame = _artifact("FirstFrameMapping", revision, {
            "shot_id": shot_order[0], "panel_id": first_panel["panel_id"], "asset_ref": first_panel["asset_ref"],
            "panel_asset_id": first_panel["panel_asset_id"], "sha256": first_panel["sha256"], "approval_ref": first_panel.get("approval_ref"), "asset_role": "clean_full_frame_panel", "aspect_ratio": first_panel["aspect_ratio"],
            **{field: first_panel.get(field, field == "clean_full_frame") for field in ("clean_full_frame", "contains_grid", "contains_number", "contains_label", "contains_caption", "contains_other_shot")},
        })
        references = self._reference_roles(value)
        role_mapping = _artifact("ReferenceRoleMapping", revision, {"references": references})
        master = _artifact("VideoGenerationStoryboardMaster", revision, {
            "product_context_bundle": product, "target_aspect_ratio": target_ratio, "shots": ordered_shots,
            "first_frame_mapping_ref": first_frame["artifact_digest"], "reference_role_mapping_ref": role_mapping["artifact_digest"],
            "master_panel_entries": master_panel_entries,
            "sheet_outputs": {"execution_policy": SHEET_EXECUTION_POLICY, "source_semantics": "master_json_read_only_projection"},
        })
        motion = _artifact("ShotMotionPlan", revision, {"shots": [{"shot_id": shot["shot_id"], "sequence": shot["sequence"], "duration_ms": shot["duration_ms"], "start_state": shot["start_state"], "middle_state": shot["middle_state"], "end_state": shot["end_state"], "motion_path": shot["motion_path"], "camera_motion": shot["camera_motion"], "transition": shot["transition"]} for shot in ordered_shots]})
        execution = _artifact("VideoExecutionPackage", revision, {
            "package_id": "vep-" + content_digest({"revision": revision, "shots": shot_order}).removeprefix("sha256:")[:20],
            "video_generation_storyboard_master": master, "shot_motion_plan": motion, "first_frame_mapping": first_frame,
            "reference_role_mapping": role_mapping, "shot_order": shot_order, "panel_order": panel_order,
            "approved_panel_refs": [entry["asset_ref"] for entry in master_panel_entries],
            "asset_mapping": [
                {"shot_id": entry["shot_id"], "panel_id": entry["panel_id"], "role": "production_panel", "asset_id": entry["panel_asset_id"], "uri": entry["asset_ref"], "sha256": entry["sha256"], "approval_state": "approved"}
                for entry in master_panel_entries
            ] + [
                {"role": item["role"], "asset_id": item["asset_ref"], "uri": item["asset_ref"], "sha256": item.get("sha256"), "approval_state": "approved", "provider_execution_input": item["provider_execution_input"]}
                for item in references if item["provider_execution_input"]
            ],
            "planning_provider_submission_performed": False,
        })
        artifacts = {"video_generation_storyboard_master": master, "shot_motion_plan": motion, "video_execution_package": execution, "first_frame_mapping": first_frame, "reference_role_mapping": role_mapping}
        return snapshot({"schema_version": SCHEMA_VERSION, "planning_revision": revision, "artifacts": artifacts, "planning_provider_submission_performed": False, "provenance": {"production_storyboard_plan_digest": content_digest(plan), "production_storyboard_panel_set_digest": content_digest(panels), "product_context_bundle_digest": content_digest(product)}})

    @staticmethod
    def _identity(value: Mapping[str, object], name: str, contract_id: str) -> None:
        artifact_name = value.get("artifact_name", value.get("artifact_type"))
        identity = value.get("contract_id", value.get("contract_identity"))
        if artifact_name != name or identity != contract_id or value.get("schema_version") != SCHEMA_VERSION:
            raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{name} identity/version is unsupported")

    @staticmethod
    def _validate_first_frame(panel: Mapping[str, object], target_ratio: str) -> None:
        asset_ref = str(panel.get("asset_ref", "")).lower()
        flags = ("contains_grid", "contains_number", "contains_label", "contains_caption", "contains_other_shot")
        explicit_clean = panel.get("clean_full_frame") is True or panel.get("first_frame_role") in {"clean_panel", "clean_first_frame", "clean_opening_frame"}
        dirty = any(panel.get(flag) is True for flag in flags)
        if not explicit_clean or panel.get("aspect_ratio") != target_ratio or dirty or any(marker in asset_ref for marker in FORBIDDEN_FIRST_FRAME_MARKERS):
            raise PlanningError(PlanningErrorCode.FIRST_FRAME_INELIGIBLE, "First frame must be one approved clean full-frame production panel")
        digest = panel.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise PlanningError(PlanningErrorCode.INVALID_INPUT, "First-frame panel digest is invalid")

    @staticmethod
    def _reference_roles(value: Mapping[str, object]) -> list[dict[str, object]]:
        roles: list[dict[str, object]] = []
        seen_refs: set[str] = set()
        for raw in _list(value.get("reference_assets", []), "reference_assets"):
            asset = _mapping(raw, "reference_assets")
            if asset.get("approval_state") != "approved" or asset.get("role") not in {"character_reference", "product_reference", "style_reference"}:
                raise PlanningError(PlanningErrorCode.REFERENCE_ROLE_FORBIDDEN, "Reference asset role or approval is invalid")
            asset_ref = _string(asset, "asset_ref", "reference_assets")
            if asset_ref in seen_refs:
                raise PlanningError(PlanningErrorCode.ASSET_MAPPING_AMBIGUOUS, "Reference asset mapping must be unique")
            digest = asset.get("sha256")
            if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
                raise PlanningError(PlanningErrorCode.INVALID_INPUT, "Reference asset digest is invalid")
            seen_refs.add(asset_ref)
            roles.append({"asset_ref": asset_ref, "sha256": asset["sha256"], "role": asset["role"], "provider_execution_input": True, "first_frame_eligible": False})
        manifest = value.get("reference_analysis_board_manifest")
        if manifest is not None:
            board = _mapping(manifest, "reference_analysis_board_manifest")
            if board.get("artifact_name") != "ReferenceAnalysisBoardManifest" or board.get("schema_version") != SCHEMA_VERSION:
                raise PlanningError(PlanningErrorCode.REFERENCE_ROLE_FORBIDDEN, "Analysis board manifest identity/version is unsupported")
            if board.get("provider_execution_input") is True or board.get("first_frame_eligible") is True:
                raise PlanningError(PlanningErrorCode.REFERENCE_ROLE_FORBIDDEN, "Analysis boards are structural-only")
            for raw in _list(board.get("assets"), "reference_analysis_board_manifest.assets"):
                asset = _mapping(raw, "reference_analysis_board_manifest.assets")
                if asset.get("provider_execution_input") is True or asset.get("first_frame_eligible") is True:
                    raise PlanningError(PlanningErrorCode.REFERENCE_ROLE_FORBIDDEN, "Analysis boards are structural-only")
                asset_ref = _string(asset, "asset_ref", "reference_analysis_board_manifest.assets")
                if asset_ref in seen_refs:
                    raise PlanningError(PlanningErrorCode.ASSET_MAPPING_AMBIGUOUS, "Reference asset mapping must be unique")
                seen_refs.add(asset_ref)
                roles.append({"asset_ref": asset_ref, "role": "global_structure_reference", "provider_execution_input": False, "first_frame_eligible": False})
        return roles
