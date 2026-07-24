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
        revision = _string(plan, "planning_revision", "production_storyboard_plan")
        product_id = _string(plan, "product_id", "production_storyboard_plan")
        if panels.get("planning_revision") != revision or panels.get("product_id") != product_id or product.get("product_id") != product_id:
            raise PlanningError(PlanningErrorCode.STALE_INPUT_VERSION, "Planning revision or product identity diverges")

        approved_results = {
            item.get("panel_id") for item in (_mapping(raw, "approved_panel_results") for raw in _list(value.get("approved_panel_results"), "approved_panel_results"))
            if item.get("approval_state") == "approved"
        }
        panel_by_shot: dict[str, dict[str, Any]] = {}
        for raw in _list(panels.get("panels"), "production_storyboard_panel_set.panels"):
            panel = _mapping(raw, "production_storyboard_panel_set.panels")
            shot_id = _string(panel, "shot_id", "panel")
            if panel.get("approval_state") != "approved" or panel.get("panel_id") not in approved_results:
                raise PlanningError(PlanningErrorCode.ASSET_NOT_APPROVED, "Every execution panel must be approved")
            if shot_id in panel_by_shot:
                raise PlanningError(PlanningErrorCode.ASSET_MAPPING_AMBIGUOUS, "Each shot must resolve to one panel")
            panel_by_shot[shot_id] = panel

        ordered_shots: list[dict[str, object]] = []
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
            panel = panel_by_shot.get(shot_id)
            if panel is None:
                raise PlanningError(PlanningErrorCode.ASSET_MAPPING_MISSING, "Every shot requires one approved panel")
            if panel.get("sequence") != shot.get("sequence"):
                raise PlanningError(PlanningErrorCode.STALE_INPUT_VERSION, "Panel and shot order diverge")
            for field in required:
                if field not in shot or (field != "cta" and (not isinstance(shot[field], (str, int)) or shot[field] == "")):
                    raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"shot.{field} is required")
            ordered_shots.append(snapshot({**shot, "panel_id": panel["panel_id"], "panel_asset_ref": panel["asset_ref"], "panel_sha256": panel["sha256"]}))
            shot_order.append(shot_id)
            panel_order.append(str(panel["panel_id"]))
        if not shot_order or sequences != set(range(1, len(shot_order) + 1)):
            raise PlanningError(PlanningErrorCode.INVALID_SHOT_ORDER, "Shots must form one contiguous non-empty sequence")
        if set(panel_by_shot) != set(shot_order):
            raise PlanningError(PlanningErrorCode.STALE_INPUT_VERSION, "Panel set contains unknown or unordered shots")

        first_panel = panel_by_shot[shot_order[0]]
        self._validate_first_frame(first_panel, str(plan.get("target_aspect_ratio")))
        first_frame = _artifact("FirstFrameMapping", revision, {
            "shot_id": shot_order[0], "panel_id": first_panel["panel_id"], "asset_ref": first_panel["asset_ref"],
            "sha256": first_panel["sha256"], "approval_ref": first_panel["approval_ref"], "aspect_ratio": first_panel["aspect_ratio"],
            **{field: first_panel[field] for field in ("clean_full_frame", "contains_grid", "contains_number", "contains_label", "contains_caption", "contains_other_shot")},
        })
        references = self._reference_roles(value)
        role_mapping = _artifact("ReferenceRoleMapping", revision, {"references": references})
        master = _artifact("VideoGenerationStoryboardMaster", revision, {
            "product_context_bundle": product, "target_aspect_ratio": plan["target_aspect_ratio"], "shots": ordered_shots,
            "first_frame_mapping_ref": first_frame["artifact_digest"], "reference_role_mapping_ref": role_mapping["artifact_digest"],
        })
        motion = _artifact("ShotMotionPlan", revision, {"shots": [{"shot_id": shot["shot_id"], "sequence": shot["sequence"], "duration_ms": shot["duration_ms"], "start_state": shot["start_state"], "middle_state": shot["middle_state"], "end_state": shot["end_state"], "motion_path": shot["motion_path"], "camera_motion": shot["camera_motion"], "transition": shot["transition"]} for shot in ordered_shots]})
        execution = _artifact("VideoExecutionPackage", revision, {
            "package_id": "vep-" + content_digest({"revision": revision, "shots": shot_order}).removeprefix("sha256:")[:20],
            "video_generation_storyboard_master": master, "shot_motion_plan": motion, "first_frame_mapping": first_frame,
            "reference_role_mapping": role_mapping, "shot_order": shot_order, "panel_order": panel_order,
            "approved_panel_refs": [panel_by_shot[shot]["asset_ref"] for shot in shot_order],
            "asset_mapping": [
                {"shot_id": shot, "panel_id": panel_by_shot[shot]["panel_id"], "role": "production_panel", "asset_id": panel_by_shot[shot]["panel_id"], "uri": panel_by_shot[shot]["asset_ref"], "sha256": panel_by_shot[shot]["sha256"], "approval_state": "approved"}
                for shot in shot_order
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
        if value.get("artifact_name") != name or value.get("contract_id") != contract_id or value.get("schema_version") != SCHEMA_VERSION:
            raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{name} identity/version is unsupported")

    @staticmethod
    def _validate_first_frame(panel: Mapping[str, object], target_ratio: str) -> None:
        asset_ref = str(panel.get("asset_ref", "")).lower()
        flags = ("contains_grid", "contains_number", "contains_label", "contains_caption", "contains_other_shot")
        if panel.get("clean_full_frame") is not True or panel.get("aspect_ratio") != target_ratio or any(panel.get(flag) is not False for flag in flags) or any(marker in asset_ref for marker in FORBIDDEN_FIRST_FRAME_MARKERS):
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
