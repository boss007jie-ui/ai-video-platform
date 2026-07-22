"""Pure deterministic Planning domain interface with no Provider seam."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .errors import PlanningError, PlanningErrorCode
from .models import CONTRACT_STATUS, SCHEMA_VERSION, content_digest, snapshot


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{field} must be an object", field_paths=(field,))
    try:
        return snapshot(value)
    except (TypeError, ValueError) as exc:
        raise PlanningError(
            PlanningErrorCode.INVALID_INPUT,
            f"{field} must contain only finite JSON-compatible values",
            field_paths=(field,),
        ) from exc


def _nonempty_string(mapping: Mapping[str, object], field: str, prefix: str = "") -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        path = f"{prefix}.{field}" if prefix else field
        raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{path} must be a non-empty string", field_paths=(path,))
    return value


def _positive_int(mapping: Mapping[str, object], field: str, prefix: str = "") -> int:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        path = f"{prefix}.{field}" if prefix else field
        raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{path} must be a positive integer", field_paths=(path,))
    return value


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise PlanningError(PlanningErrorCode.INVALID_INPUT, f"{field} must be an array", field_paths=(field,))
    return list(value)


class VideoPlanningInterface:
    """Compose local draft board and execution artifacts without side effects."""

    def compose_storyboard_master(self, request: Mapping[str, object]) -> dict[str, object]:
        context = self._validate_request(request)
        board, asset_mapping, anchors, motion_plan = self._compose(context)
        body: dict[str, object] = {
            "artifact_name": "StoryboardMaster",
            "schema_version": SCHEMA_VERSION,
            "contract_status": CONTRACT_STATUS,
            "task_id": context["task_id"],
            "source": context["source"],
            "shots": board,
            "asset_mapping": asset_mapping,
            "visual_anchors": anchors,
            "motion_plan": motion_plan,
            "planning_provider_submission_performed": False,
        }
        return snapshot({**body, "master_digest": content_digest(body)})

    def build_video_plan(self, request: Mapping[str, object]) -> dict[str, object]:
        master = self.compose_storyboard_master(request)
        source = snapshot(master["source"])
        package_id = "vep-" + content_digest(source).removeprefix("sha256:")[:20]
        body: dict[str, object] = {
            "artifact_name": "VideoExecutionPackage",
            "schema_version": SCHEMA_VERSION,
            "contract_status": CONTRACT_STATUS,
            "package_id": package_id,
            "task_id": master["task_id"],
            "source": source,
            "storyboard_master": master,
            "asset_mapping": snapshot(master["asset_mapping"]),
            "visual_anchors": snapshot(master["visual_anchors"]),
            "motion_plan": snapshot(master["motion_plan"]),
            "planning_provider_submission_performed": False,
        }
        return snapshot({**body, "package_digest": content_digest(body)})

    def validate_video_plan(self, package: Mapping[str, object]) -> dict[str, str]:
        candidate = _mapping(package, "package")
        if candidate.get("planning_provider_submission_performed") is not False:
            raise PlanningError(
                PlanningErrorCode.PROVIDER_SUBMISSION_FORBIDDEN,
                "Planning artifacts cannot record Provider submission",
                field_paths=("planning_provider_submission_performed",),
            )
        required = {
            "artifact_name", "schema_version", "contract_status", "package_id", "task_id", "source",
            "storyboard_master", "asset_mapping", "visual_anchors", "motion_plan", "package_digest",
        }
        if required - set(candidate):
            raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "VideoExecutionPackage is incomplete")
        if candidate["artifact_name"] != "VideoExecutionPackage" or candidate["schema_version"] != SCHEMA_VERSION:
            raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "VideoExecutionPackage identity or version is unsupported")
        if candidate["contract_status"] != CONTRACT_STATUS:
            raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "Business artifact must remain DRAFT_UNREGISTERED")
        for field in ("asset_mapping", "motion_plan"):
            if not isinstance(candidate[field], list) or not candidate[field]:
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, f"{field} must be non-empty", field_paths=(field,))
        master = _mapping(candidate["storyboard_master"], "storyboard_master")
        master_digest = master.pop("master_digest", None)
        if not isinstance(master_digest, str) or content_digest(master) != master_digest:
            raise PlanningError(PlanningErrorCode.PACKAGE_TAMPERED, "StoryboardMaster digest mismatch")
        try:
            self._validate_master_structure(master)
        except PlanningError as error:
            if error.code in {
                PlanningErrorCode.PACKAGE_INVALID,
                PlanningErrorCode.PACKAGE_TAMPERED,
                PlanningErrorCode.PROVIDER_SUBMISSION_FORBIDDEN,
            }:
                raise
            raise PlanningError(
                PlanningErrorCode.PACKAGE_INVALID,
                "StoryboardMaster structure is invalid",
                field_paths=error.field_paths,
            ) from error
        if master.get("planning_provider_submission_performed") is not False:
            raise PlanningError(
                PlanningErrorCode.PROVIDER_SUBMISSION_FORBIDDEN,
                "Nested Planning artifact cannot record Provider submission",
            )
        expected_package_id = "vep-" + content_digest(candidate["source"]).removeprefix("sha256:")[:20]
        if candidate["package_id"] != expected_package_id:
            raise PlanningError(PlanningErrorCode.PACKAGE_TAMPERED, "VideoExecutionPackage identifier does not match its source")
        if candidate["task_id"] != master.get("task_id") or candidate["source"] != master.get("source"):
            raise PlanningError(PlanningErrorCode.PACKAGE_TAMPERED, "Execution package source disagrees with StoryboardMaster")
        if (
            candidate["asset_mapping"] != master.get("asset_mapping")
            or candidate["visual_anchors"] != master.get("visual_anchors")
            or candidate["motion_plan"] != master.get("motion_plan")
        ):
            raise PlanningError(PlanningErrorCode.PACKAGE_TAMPERED, "Execution package disagrees with StoryboardMaster")
        supplied = candidate.pop("package_digest")
        if not isinstance(supplied, str) or content_digest(candidate) != supplied:
            raise PlanningError(PlanningErrorCode.PACKAGE_TAMPERED, "VideoExecutionPackage digest mismatch")
        return {
            "status": "valid",
            "schema_version": SCHEMA_VERSION,
            "contract_status": CONTRACT_STATUS,
            "package_digest": supplied,
        }

    def _validate_master_structure(self, master: Mapping[str, object]) -> None:
        if (
            master.get("artifact_name") != "StoryboardMaster"
            or master.get("schema_version") != SCHEMA_VERSION
            or master.get("contract_status") != CONTRACT_STATUS
        ):
            raise PlanningError(PlanningErrorCode.PACKAGE_TAMPERED, "Nested StoryboardMaster identity is invalid")
        _nonempty_string(master, "task_id", "storyboard_master")
        source = _mapping(master.get("source"), "storyboard_master.source")
        for field in ("storyboard_id", "asset_manifest_id"):
            _nonempty_string(source, field, "storyboard_master.source")
        for field in ("storyboard_revision", "asset_manifest_revision"):
            _positive_int(source, field, "storyboard_master.source")
        for field in ("storyboard_digest", "asset_manifest_digest"):
            digest_value = _nonempty_string(source, field, "storyboard_master.source")
            if re.fullmatch(r"sha256:[0-9a-f]{64}", digest_value) is None:
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, f"storyboard_master.source.{field} is invalid")

        shots = _list(master.get("shots"), "storyboard_master.shots")
        mappings = _list(master.get("asset_mapping"), "storyboard_master.asset_mapping")
        anchors = _list(master.get("visual_anchors"), "storyboard_master.visual_anchors")
        motions = _list(master.get("motion_plan"), "storyboard_master.motion_plan")
        if not shots or not mappings or not anchors or not motions:
            raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster planning structures must be non-empty")

        shot_by_id: dict[str, dict[str, Any]] = {}
        sequence_values: set[int] = set()
        expected_pairs: set[tuple[str, str]] = set()
        expected_anchors: dict[str, dict[str, Any]] = {}
        for index, raw_shot in enumerate(shots):
            shot = _mapping(raw_shot, f"storyboard_master.shots[{index}]")
            shot_id = _nonempty_string(shot, "shot_id", f"storyboard_master.shots[{index}]")
            sequence = _positive_int(shot, "sequence", f"storyboard_master.shots[{index}]")
            if shot_id in shot_by_id or sequence in sequence_values:
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster shot identity/order is ambiguous")
            sequence_values.add(sequence)
            roles = _list(shot.get("required_asset_roles"), f"storyboard_master.shots[{index}].required_asset_roles")
            if not roles or any(not isinstance(role, str) or not role.strip() for role in roles) or len(set(roles)) != len(roles):
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster required roles are invalid")
            group = _nonempty_string(shot, "continuity_group", f"storyboard_master.shots[{index}]")
            anchor = _mapping(shot.get("visual_anchor"), f"storyboard_master.shots[{index}].visual_anchor")
            motion = _mapping(shot.get("motion"), f"storyboard_master.shots[{index}].motion")
            if group in expected_anchors and expected_anchors[group] != anchor:
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster continuity anchors conflict")
            expected_anchors[group] = anchor
            expected_pairs.update((shot_id, role) for role in roles)
            shot_by_id[shot_id] = {"sequence": sequence, "motion": motion}

        actual_pairs: set[tuple[str, str]] = set()
        for index, raw_mapping in enumerate(mappings):
            item = _mapping(raw_mapping, f"storyboard_master.asset_mapping[{index}]")
            shot_id = _nonempty_string(item, "shot_id", "storyboard_master.asset_mapping")
            role = _nonempty_string(item, "role", "storyboard_master.asset_mapping")
            _nonempty_string(item, "asset_id", "storyboard_master.asset_mapping")
            _nonempty_string(item, "uri", "storyboard_master.asset_mapping")
            digest_value = _nonempty_string(item, "sha256", "storyboard_master.asset_mapping")
            if re.fullmatch(r"sha256:[0-9a-f]{64}", digest_value) is None:
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster asset digest is invalid")
            pair = (shot_id, role)
            if pair in actual_pairs:
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster asset mapping is ambiguous")
            actual_pairs.add(pair)
        if actual_pairs != expected_pairs:
            raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster asset mapping is incomplete")

        actual_anchors: dict[str, dict[str, Any]] = {}
        for index, raw_anchor in enumerate(anchors):
            item = _mapping(raw_anchor, f"storyboard_master.visual_anchors[{index}]")
            group = _nonempty_string(item, "continuity_group", "storyboard_master.visual_anchors")
            if group in actual_anchors:
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster visual anchors are ambiguous")
            actual_anchors[group] = _mapping(item.get("anchor"), "storyboard_master.visual_anchors.anchor")
        if actual_anchors != expected_anchors:
            raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster visual anchors are incomplete")

        seen_motion: set[str] = set()
        for index, raw_motion in enumerate(motions):
            item = _mapping(raw_motion, f"storyboard_master.motion_plan[{index}]")
            shot_id = _nonempty_string(item, "shot_id", "storyboard_master.motion_plan")
            sequence = _positive_int(item, "sequence", "storyboard_master.motion_plan")
            motion = _mapping(item.get("motion"), "storyboard_master.motion_plan.motion")
            if shot_id in seen_motion or shot_id not in shot_by_id:
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster motion plan contains an unknown or duplicate shot")
            if sequence != shot_by_id[shot_id]["sequence"] or motion != shot_by_id[shot_id]["motion"]:
                raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster motion plan disagrees with board")
            seen_motion.add(shot_id)
        if seen_motion != set(shot_by_id):
            raise PlanningError(PlanningErrorCode.PACKAGE_INVALID, "StoryboardMaster motion plan is incomplete")

    def _validate_request(self, request: Mapping[str, object]) -> dict[str, Any]:
        value = _mapping(request, "request")
        task_id = _nonempty_string(value, "task_id")
        storyboard = _mapping(value.get("storyboard"), "storyboard")
        manifest = _mapping(value.get("asset_manifest"), "asset_manifest")
        storyboard_id = _nonempty_string(storyboard, "storyboard_id", "storyboard")
        storyboard_revision = _positive_int(storyboard, "revision", "storyboard")
        manifest_id = _nonempty_string(manifest, "manifest_id", "asset_manifest")
        manifest_revision = _positive_int(manifest, "manifest_revision", "asset_manifest")
        expected_storyboard = _positive_int(value, "expected_storyboard_revision")
        expected_manifest = _positive_int(value, "expected_asset_manifest_revision")
        if expected_storyboard != storyboard_revision or expected_manifest != manifest_revision:
            raise PlanningError(
                PlanningErrorCode.STALE_INPUT_VERSION,
                "Expected revisions do not match the supplied Storyboard and AssetManifest",
                field_paths=("expected_storyboard_revision", "expected_asset_manifest_revision"),
            )
        if manifest.get("storyboard_id") != storyboard_id or manifest.get("storyboard_revision") != storyboard_revision:
            raise PlanningError(PlanningErrorCode.STALE_INPUT_VERSION, "AssetManifest targets a different Storyboard revision")
        shots = _list(storyboard.get("shots"), "storyboard.shots")
        assets = _list(manifest.get("assets"), "asset_manifest.assets")
        if not shots:
            raise PlanningError(PlanningErrorCode.INVALID_INPUT, "storyboard.shots must be non-empty")
        return {
            "task_id": task_id,
            "storyboard": storyboard,
            "manifest": manifest,
            "shots": shots,
            "assets": assets,
            "source": {
                "storyboard_id": storyboard_id,
                "storyboard_revision": storyboard_revision,
                "storyboard_digest": content_digest(storyboard),
                "asset_manifest_id": manifest_id,
                "asset_manifest_revision": manifest_revision,
                "asset_manifest_digest": content_digest(manifest),
            },
        }

    def _compose(self, context: Mapping[str, Any]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        normalized_shots: list[dict[str, Any]] = []
        shot_ids: set[str] = set()
        sequences: set[int] = set()
        anchor_by_group: dict[str, dict[str, Any]] = {}
        for index, raw in enumerate(context["shots"]):
            shot = _mapping(raw, f"storyboard.shots[{index}]")
            shot_id = _nonempty_string(shot, "shot_id", f"storyboard.shots[{index}]")
            sequence = _positive_int(shot, "sequence", f"storyboard.shots[{index}]")
            if shot_id in shot_ids or sequence in sequences:
                raise PlanningError(PlanningErrorCode.SHOT_SEQUENCE_INVALID, "Shot IDs and sequences must be unique")
            shot_ids.add(shot_id)
            sequences.add(sequence)
            roles = _list(shot.get("required_asset_roles"), f"storyboard.shots[{index}].required_asset_roles")
            if not roles or any(not isinstance(role, str) or not role.strip() for role in roles) or len(set(roles)) != len(roles):
                raise PlanningError(PlanningErrorCode.INVALID_INPUT, "required_asset_roles must contain one or more unique strings")
            group = _nonempty_string(shot, "continuity_group", f"storyboard.shots[{index}]")
            anchor = _mapping(shot.get("visual_anchor"), f"storyboard.shots[{index}].visual_anchor")
            motion = _mapping(shot.get("motion"), f"storyboard.shots[{index}].motion")
            if group in anchor_by_group and anchor_by_group[group] != anchor:
                raise PlanningError(PlanningErrorCode.CONTINUITY_CONFLICT, "Continuity group contains conflicting visual anchors")
            anchor_by_group[group] = anchor
            normalized_shots.append({
                "shot_id": shot_id,
                "sequence": sequence,
                "required_asset_roles": sorted(roles),
                "continuity_group": group,
                "visual_anchor": anchor,
                "motion": motion,
            })
        normalized_shots.sort(key=lambda item: (item["sequence"], item["shot_id"]))
        normalized_assets = [_mapping(asset, f"asset_manifest.assets[{i}]") for i, asset in enumerate(context["assets"])]
        mapping: list[dict[str, object]] = []
        for shot in normalized_shots:
            for role in shot["required_asset_roles"]:
                candidates = [
                    asset for asset in normalized_assets
                    if asset.get("role") == role and shot["shot_id"] in _list(asset.get("shot_ids", []), "asset.shot_ids")
                ]
                if not candidates:
                    raise PlanningError(PlanningErrorCode.ASSET_MAPPING_MISSING, "Required shot asset mapping is missing")
                if len(candidates) > 1:
                    raise PlanningError(PlanningErrorCode.ASSET_MAPPING_AMBIGUOUS, "Required shot asset mapping is ambiguous")
                asset = candidates[0]
                asset_id = _nonempty_string(asset, "asset_id", "asset_manifest.assets")
                if asset.get("approval_state") != "approved":
                    raise PlanningError(PlanningErrorCode.ASSET_NOT_APPROVED, "Mapped asset is not approved")
                uri = _nonempty_string(asset, "uri", "asset_manifest.assets")
                sha256 = _nonempty_string(asset, "sha256", "asset_manifest.assets")
                if re.fullmatch(r"sha256:[0-9a-f]{64}", sha256) is None:
                    raise PlanningError(PlanningErrorCode.INVALID_INPUT, "Mapped asset sha256 is invalid")
                mapping.append({"shot_id": shot["shot_id"], "role": role, "asset_id": asset_id, "uri": uri, "sha256": sha256})
        anchors = [
            {"continuity_group": group, "anchor": anchor_by_group[group]}
            for group in sorted(anchor_by_group)
        ]
        motion_plan = [
            {"shot_id": shot["shot_id"], "sequence": shot["sequence"], "motion": shot["motion"]}
            for shot in normalized_shots
        ]
        return normalized_shots, mapping, anchors, motion_plan
