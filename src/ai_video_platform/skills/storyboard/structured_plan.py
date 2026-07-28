"""Validation for the frozen owner-local structured storyboard plan."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ai_video_platform.contracts.serialization import content_digest, freeze_json, thaw_json

from .interface import StoryboardError


SHOT_REQUIRED_FIELDS = (
    "start_state",
    "action_path",
    "end_state",
    "emotion_transition",
    "audience_psychology",
    "conversion_function",
    "dialogue_or_voiceover",
    "subtitle",
    "sound_design",
    "transition",
    "required_assets",
    "forbidden_assets",
    "first_frame_role",
    "provider_reference_role",
)

PRODUCT_CONTINUITY_FIELDS = (
    "active_product_id",
    "active_sku_id",
    "visible_sku_ids",
    "forbidden_sku_ids",
    "product_state",
    "package_state",
    "container_state",
    "scale_constraints",
)


def _fail(code: str, message: str, *paths: str) -> None:
    raise StoryboardError(code, "validation", message, field_paths=tuple(paths))


def _object(value: object, path: str, code: str = "STORYBOARD_STRUCTURE_INVALID") -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(code, "Structured storyboard value must be an object", path)
    return dict(value)


def _array(value: object, path: str, code: str = "STORYBOARD_STRUCTURE_INVALID") -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail(code, "Structured storyboard value must be an array", path)
    return list(value)


def _integer(value: object, path: str, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(code, "Storyboard timing and sequence values must be integer milliseconds", path)
    return value


def _text(value: object, path: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(code, "Structured storyboard semantic text must be explicit", path)
    return value.strip()


def _string_array(value: object, path: str, code: str) -> list[str]:
    values = _array(value, path, code)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        _fail(code, "Storyboard identifier and asset arrays require non-empty strings", path)
    return [item.strip() for item in values]


def _validate_profile(plan: dict[str, Any], shot_count: int) -> None:
    profile = _text(plan.get("workflow_profile"), "workflow_profile", "STORYBOARD_PROFILE_INVALID")
    if profile == "short_form":
        minimum, maximum = 5, 9
    else:
        rules = _object(
            plan.get("workflow_profile_rules"),
            "workflow_profile_rules",
            "STORYBOARD_PROFILE_INVALID",
        )
        selected = _object(rules.get(profile), f"workflow_profile_rules.{profile}", "STORYBOARD_PROFILE_INVALID")
        minimum = _integer(selected.get("min_shots"), f"workflow_profile_rules.{profile}.min_shots", "STORYBOARD_PROFILE_INVALID")
        maximum = _integer(selected.get("max_shots"), f"workflow_profile_rules.{profile}.max_shots", "STORYBOARD_PROFILE_INVALID")
        if minimum < 1 or maximum < minimum:
            _fail("STORYBOARD_PROFILE_INVALID", "Workflow profile Shot bounds are invalid", f"workflow_profile_rules.{profile}")
    if not minimum <= shot_count <= maximum:
        _fail(
            "STORYBOARD_PROFILE_INVALID",
            "Shot count does not satisfy the selected workflow profile",
            "workflow_profile",
            "shots",
        )


def _validate_scope(plan: dict[str, Any], task_spec_payload: Mapping[str, Any]) -> dict[str, Any]:
    scope = _object(plan.get("product_scope"), "product_scope", "STORYBOARD_PRODUCT_SCOPE_INVALID")
    mode = _text(scope.get("mode"), "product_scope.mode", "STORYBOARD_PRODUCT_SCOPE_INVALID")
    if mode not in {"single_sku", "multi_sku"}:
        _fail("STORYBOARD_PRODUCT_SCOPE_INVALID", "Product scope mode is not supported", "product_scope.mode")
    active_product = _text(
        scope.get("active_product_id"),
        "product_scope.active_product_id",
        "STORYBOARD_PRODUCT_SCOPE_INVALID",
    )
    active_sku = _text(scope.get("active_sku_id"), "product_scope.active_sku_id", "STORYBOARD_PRODUCT_SCOPE_INVALID")
    allowed = _string_array(
        scope.get("allowed_sku_ids"),
        "product_scope.allowed_sku_ids",
        "STORYBOARD_PRODUCT_SCOPE_INVALID",
    )
    if len(set(allowed)) != len(allowed) or active_sku not in allowed:
        _fail("STORYBOARD_PRODUCT_SCOPE_INVALID", "Allowed SKU scope is inconsistent", "product_scope.allowed_sku_ids")
    if mode == "single_sku" and allowed != [active_sku]:
        _fail("STORYBOARD_PRODUCT_SCOPE_INVALID", "Single-SKU scope may allow only the active SKU", "product_scope.allowed_sku_ids")
    if mode == "multi_sku":
        constraints = task_spec_payload.get("constraints", {})
        storyboard = constraints.get("storyboard", {}) if isinstance(constraints, Mapping) else {}
        authorized = storyboard.get("product_scope", {}) if isinstance(storyboard, Mapping) else {}
        authorized_allowed = authorized.get("allowed_sku_ids", ()) if isinstance(authorized, Mapping) else ()
        if (
            not isinstance(authorized, Mapping)
            or authorized.get("mode") != "multi_sku"
            or not isinstance(authorized_allowed, Sequence)
            or isinstance(authorized_allowed, (str, bytes, bytearray))
            or set(allowed) - set(authorized_allowed)
        ):
            _fail(
                "STORYBOARD_SKU_SCOPE_UNAUTHORIZED",
                "TaskSpec does not explicitly authorize this multi-SKU scope",
                "product_scope.mode",
                "task_spec.constraints.storyboard.product_scope",
            )
    return {**scope, "mode": mode, "active_product_id": active_product, "active_sku_id": active_sku, "allowed_sku_ids": allowed}


def _validate_motion(shot: dict[str, Any], shot_path: str) -> None:
    signatures: list[tuple[str, str, str, str]] = []
    for field in ("camera_motion", "subject_motion"):
        path = f"{shot_path}.{field}"
        motion = _object(shot.get(field), path, "STORYBOARD_MOTION_ANNOTATION_INVALID")
        _text(motion.get("structured_definition"), f"{path}.structured_definition", "STORYBOARD_MOTION_ANNOTATION_INVALID")
        visual = _object(motion.get("visual_annotation"), f"{path}.visual_annotation", "STORYBOARD_MOTION_ANNOTATION_INVALID")
        label = _text(visual.get("label"), f"{path}.visual_annotation.label", "STORYBOARD_MOTION_ANNOTATION_INVALID")
        non_color = tuple(str(visual.get(key, "")).strip() for key in ("line_style", "marker", "arrow_form"))
        if not any(non_color):
            _fail(
                "STORYBOARD_MOTION_ANNOTATION_INVALID",
                "Motion annotations require a non-color visual encoding",
                f"{path}.visual_annotation",
            )
        signatures.append((label.casefold(), *(item.casefold() for item in non_color)))
    if signatures[0] == signatures[1]:
        _fail(
            "STORYBOARD_MOTION_ANNOTATION_INVALID",
            "Camera and subject motion must remain distinguishable without color",
            f"{shot_path}.camera_motion.visual_annotation",
            f"{shot_path}.subject_motion.visual_annotation",
        )


def _validate_transition(shot: dict[str, Any], shot_path: str, duration_ms: int) -> None:
    transition = _object(shot.get("transition"), f"{shot_path}.transition", "STORYBOARD_TRANSITION_INVALID")
    kind = _text(transition.get("kind"), f"{shot_path}.transition.kind", "STORYBOARD_TRANSITION_INVALID")
    transition_duration = _integer(
        transition.get("duration_ms"),
        f"{shot_path}.transition.duration_ms",
        "STORYBOARD_TRANSITION_INVALID",
    )
    policy = _text(
        transition.get("timing_policy"),
        f"{shot_path}.transition.timing_policy",
        "STORYBOARD_TRANSITION_INVALID",
    )
    if transition_duration < 0 or transition_duration > duration_ms or "overlap" in policy.casefold():
        _fail("STORYBOARD_TRANSITION_INVALID", "Transition timing cannot overlap the Shot timeline", f"{shot_path}.transition")
    if kind == "none" and (transition_duration != 0 or policy != "none"):
        _fail("STORYBOARD_TRANSITION_INVALID", "No-transition semantics must be explicit and zero-duration", f"{shot_path}.transition")
    if kind != "none" and (transition_duration == 0 or policy == "none"):
        _fail("STORYBOARD_TRANSITION_INVALID", "Visual transitions require an explicit duration and timing policy", f"{shot_path}.transition")


def _validate_panels(shot: dict[str, Any], shot_path: str) -> list[dict[str, Any]]:
    panels = [_object(item, f"{shot_path}.panels[{index}]", "STORYBOARD_PANEL_TIMING_INVALID") for index, item in enumerate(_array(shot.get("panels"), f"{shot_path}.panels", "STORYBOARD_PANEL_TIMING_INVALID"))]
    if not panels:
        _fail("STORYBOARD_PANEL_TIMING_INVALID", "Every Shot requires at least one Panel", f"{shot_path}.panels")
    segments: list[tuple[int, int]] = []
    anchors: set[tuple[int, str]] = set()
    for index, panel in enumerate(panels, 1):
        path = f"{shot_path}.panels[{index - 1}]"
        if panel.get("panel_sequence") != index or panel.get("panel_id") != f"{shot['shot_id']}-P{index:02d}":
            _fail("STORYBOARD_SEQUENCE_INVALID", "Panel IDs and sequences must be contiguous within their Shot", f"{path}.panel_id", f"{path}.panel_sequence")
        if panel.get("shot_id") != shot["shot_id"] or panel.get("beat_id") != shot["beat_id"]:
            _fail("STORYBOARD_HIERARCHY_INVALID", "Panel parent IDs must match its Shot and Beat", f"{path}.shot_id", f"{path}.beat_id")
        mode = panel.get("panel_timing_mode")
        if mode == "TEMPORAL_SEGMENT":
            start = _integer(panel.get("start_ms"), f"{path}.start_ms", "STORYBOARD_PANEL_TIMING_INVALID")
            end = _integer(panel.get("end_ms"), f"{path}.end_ms", "STORYBOARD_PANEL_TIMING_INVALID")
            duration = _integer(panel.get("duration_ms"), f"{path}.duration_ms", "STORYBOARD_PANEL_TIMING_INVALID")
            if end <= start or end - start != duration or start < shot["start_ms"] or end > shot["end_ms"]:
                _fail("STORYBOARD_PANEL_TIMING_INVALID", "Temporal Panel timing is outside or inconsistent with its Shot", path)
            if "anchor_time_ms" in panel or "anchor_role" in panel:
                _fail("STORYBOARD_PANEL_TIMING_INVALID", "Temporal Panels cannot publish keyframe timing", path)
            segments.append((start, end))
        elif mode == "KEYFRAME_ANCHOR":
            anchor = _integer(panel.get("anchor_time_ms"), f"{path}.anchor_time_ms", "STORYBOARD_PANEL_TIMING_INVALID")
            role = _text(panel.get("anchor_role"), f"{path}.anchor_role", "STORYBOARD_PANEL_TIMING_INVALID")
            if anchor < shot["start_ms"] or anchor > shot["end_ms"] or any(key in panel for key in ("start_ms", "end_ms", "duration_ms")):
                _fail("STORYBOARD_PANEL_TIMING_INVALID", "Keyframe Panels cannot claim duration or leave their Shot", path)
            if (anchor, role) in anchors:
                _fail("STORYBOARD_PANEL_TIMING_INVALID", "Keyframe anchors must be distinct", path)
            anchors.add((anchor, role))
        else:
            _fail("STORYBOARD_PANEL_TIMING_INVALID", "Panel timing mode is not supported", f"{path}.panel_timing_mode")
    if segments:
        ordered = sorted(segments)
        expected = shot["start_ms"]
        for start, end in ordered:
            if start != expected:
                _fail("STORYBOARD_PANEL_TIMING_INVALID", "Temporal Panels must continuously cover the parent Shot", f"{shot_path}.panels")
            expected = end
        if expected != shot["end_ms"]:
            _fail("STORYBOARD_PANEL_TIMING_INVALID", "Temporal Panels must continuously cover the parent Shot", f"{shot_path}.panels")
    return panels


def _source_text(value: object, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def project_storyboard_artifact(
    artifact: Mapping[str, Any],
    *,
    task_id: str,
    product_id: str,
    sku_id: str,
    total_duration_ms: int,
    required_assets: Sequence[str] = (),
    forbidden_assets: Sequence[str] = (),
    scale_constraints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project an owner-local StoryboardArtifact into the strict production shape."""

    source = thaw_json(freeze_json(_object(artifact, "storyboard_artifact", "STORYBOARD_ARTIFACT_INVALID")))
    story = _object(source.get("story"), "storyboard_artifact.story", "STORYBOARD_ARTIFACT_INVALID")
    if (
        source.get("task_id") != task_id
        or source.get("product_id") != product_id
        or story.get("product_id") != product_id
        or not isinstance(source.get("version"), int)
        or isinstance(source.get("version"), bool)
        or source["version"] < 1
        or source.get("content_digest") != content_digest(story)
    ):
        _fail(
            "STORYBOARD_ARTIFACT_INVALID",
            "StoryboardArtifact identity or digest does not match the current task",
            "storyboard_artifact",
        )
    if not isinstance(total_duration_ms, int) or isinstance(total_duration_ms, bool) or total_duration_ms < 1:
        _fail("STORYBOARD_DURATION_MISMATCH", "Production duration must be a positive integer", "production_constraints.duration_ms")
    _text(sku_id, "product_context.payload.sku_id", "STORYBOARD_PRODUCT_SCOPE_INVALID")
    required = _string_array(required_assets, "creative_constraints.required_assets", "STORYBOARD_SHOT_FIELDS_MISSING")
    forbidden = _string_array(forbidden_assets, "creative_constraints.forbidden_assets", "STORYBOARD_SHOT_FIELDS_MISSING")

    source_beats: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = []
    for scene_index, raw_scene in enumerate(_array(story.get("scenes"), "storyboard_artifact.story.scenes", "STORYBOARD_ARTIFACT_INVALID")):
        scene = _object(raw_scene, f"storyboard_artifact.story.scenes[{scene_index}]", "STORYBOARD_ARTIFACT_INVALID")
        for beat_index, raw_beat in enumerate(_array(scene.get("beats"), f"storyboard_artifact.story.scenes[{scene_index}].beats", "STORYBOARD_ARTIFACT_INVALID")):
            beat = _object(raw_beat, f"storyboard_artifact.story.scenes[{scene_index}].beats[{beat_index}]", "STORYBOARD_ARTIFACT_INVALID")
            source_shots = [
                _object(raw_shot, f"storyboard_artifact.story.scenes[{scene_index}].beats[{beat_index}].shots[{shot_index}]", "STORYBOARD_ARTIFACT_INVALID")
                for shot_index, raw_shot in enumerate(_array(beat.get("shots"), f"storyboard_artifact.story.scenes[{scene_index}].beats[{beat_index}].shots", "STORYBOARD_ARTIFACT_INVALID"))
            ]
            if not source_shots:
                _fail("STORYBOARD_ARTIFACT_INVALID", "Every source Beat requires a Shot", "storyboard_artifact.story")
            source_beats.append((scene, beat, source_shots))
    shot_count = sum(len(shots) for _, _, shots in source_beats)
    if not source_beats or shot_count < 1 or total_duration_ms < shot_count:
        _fail("STORYBOARD_DURATION_MISMATCH", "StoryboardArtifact duration cannot cover its Shots", "production_constraints.duration_ms")

    base_duration, remainder = divmod(total_duration_ms, shot_count)
    durations = [base_duration + (1 if index < remainder else 0) for index in range(shot_count)]
    beats: list[dict[str, Any]] = []
    shots: list[dict[str, Any]] = []
    shot_index = 0
    current_ms = 0
    prior_continuity: dict[str, Any] | None = None
    normalized_scale = thaw_json(freeze_json(scale_constraints or {}))
    for beat_index, (scene, beat, source_shots) in enumerate(source_beats, 1):
        beat_id = f"B{beat_index:02d}"
        generated_shot_ids = [f"S{shot_index + offset + 1:02d}" for offset in range(len(source_shots))]
        beats.append({"beat_id": beat_id, "beat_sequence": beat_index, "shot_ids": generated_shot_ids})
        for source_shot in source_shots:
            generated_shot_id = f"S{shot_index + 1:02d}"
            duration = durations[shot_index]
            start_ms = current_ms
            end_ms = start_ms + duration
            source_panels = [
                _object(raw_panel, f"storyboard_artifact.story.shots[{shot_index}].panels[{panel_index}]", "STORYBOARD_ARTIFACT_INVALID")
                for panel_index, raw_panel in enumerate(_array(source_shot.get("panels"), f"storyboard_artifact.story.shots[{shot_index}].panels", "STORYBOARD_ARTIFACT_INVALID"))
            ]
            if not source_panels:
                _fail("STORYBOARD_ARTIFACT_INVALID", "Every source Shot requires a Panel", "storyboard_artifact.story")
            source_panel = source_panels[0]
            source_continuity = _object(source_panel.get("continuity"), f"storyboard_artifact.story.shots[{shot_index}].panels[0].continuity", "STORYBOARD_ARTIFACT_INVALID")
            action = _text(beat.get("action"), f"storyboard_artifact.story.beats[{beat_index - 1}].action", "STORYBOARD_ARTIFACT_INVALID")
            prompt = _text(source_panel.get("prompt"), f"storyboard_artifact.story.shots[{shot_index}].panels[0].prompt", "STORYBOARD_ARTIFACT_INVALID")
            framing = _text(source_shot.get("framing"), f"storyboard_artifact.story.shots[{shot_index}].framing", "STORYBOARD_ARTIFACT_INVALID")
            scene_state = _source_text(source_continuity.get("scene_state", source_continuity.get("scene_background")), _source_text(scene.get("setting"), "source storyboard scene"))
            character_state = _source_text(source_continuity.get("character_state", source_continuity.get("hand", source_continuity.get("actor_outfit"))), "source storyboard character")
            continuity = {
                "active_product_id": product_id,
                "active_sku_id": sku_id,
                "product_state": _source_text(source_continuity.get("product_state", source_continuity.get("product_identity")), prompt),
                "package_state": _source_text(source_continuity.get("package_state"), "source storyboard package state"),
                "container_state": _source_text(source_continuity.get("container_state"), "source storyboard container state"),
                "scale_constraints": normalized_scale,
                "character_state": character_state,
                "wardrobe_state": _source_text(source_continuity.get("wardrobe_state", source_continuity.get("actor_outfit")), character_state),
                "scene_state": scene_state,
            }
            panel_base, panel_remainder = divmod(duration, len(source_panels))
            panel_start = start_ms
            projected_panels = []
            for panel_index, panel in enumerate(source_panels, 1):
                panel_duration = panel_base + (1 if panel_index <= panel_remainder else 0)
                panel_end = panel_start + panel_duration
                projected_panels.append({
                    "beat_id": beat_id,
                    "shot_id": generated_shot_id,
                    "panel_id": f"{generated_shot_id}-P{panel_index:02d}",
                    "panel_sequence": panel_index,
                    "panel_timing_mode": "TEMPORAL_SEGMENT",
                    "start_ms": panel_start,
                    "end_ms": panel_end,
                    "duration_ms": panel_duration,
                    "prompt": _text(panel.get("prompt"), f"storyboard_artifact.story.shots[{shot_index}].panels[{panel_index - 1}].prompt", "STORYBOARD_ARTIFACT_INVALID"),
                    "source_panel_id": panel.get("panel_id"),
                })
                panel_start = panel_end
            projected_shot = {
                "beat_id": beat_id,
                "shot_id": generated_shot_id,
                "shot_sequence": shot_index + 1,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": duration,
                "start_state": _source_text(source_shot.get("start_state"), prompt),
                "action_path": action,
                "middle_state": action,
                "end_state": _source_text(source_shot.get("end_state"), action),
                "motion_path": action,
                "emotion_transition": _source_text(source_shot.get("emotion_transition"), _source_text(scene.get("emotion"), "engaged")),
                "emotion": _source_text(scene.get("emotion"), "engaged"),
                "audience_psychology": _source_text(source_shot.get("audience_psychology"), "retain attention"),
                "conversion_function": _source_text(source_shot.get("conversion_function"), "hook" if shot_index == 0 else "cta" if shot_index == shot_count - 1 else "proof"),
                "dialogue_or_voiceover": _source_text(source_shot.get("dialogue_or_voiceover", source_shot.get("voiceover")), "none"),
                "voiceover": _source_text(source_shot.get("dialogue_or_voiceover", source_shot.get("voiceover")), "none"),
                "subtitle": _source_text(source_shot.get("subtitle", source_shot.get("caption")), "none"),
                "caption": _source_text(source_shot.get("subtitle", source_shot.get("caption")), "none"),
                "sound_design": _source_text(source_shot.get("sound_design", source_shot.get("sound_effect")), "none"),
                "sound_effect": _source_text(source_shot.get("sound_design", source_shot.get("sound_effect")), "none"),
                "cta": _source_text(source_shot.get("cta"), ""),
                "transition": {"kind": "none", "duration_ms": 0, "timing_policy": "none"},
                "required_assets": list(required),
                "forbidden_assets": list(forbidden),
                "first_frame_role": "clean_panel" if shot_index == 0 else "production_panel",
                "provider_reference_role": "product_reference",
                "camera_motion": {
                    "structured_definition": f"locked {framing}",
                    "visual_annotation": {"label": "CAMERA", "line_style": "solid", "marker": "triangle", "arrow_form": "open"},
                },
                "subject_motion": {
                    "structured_definition": action,
                    "visual_annotation": {"label": "SUBJECT", "line_style": "dashed", "marker": "circle", "arrow_form": "filled"},
                },
                "active_product_id": product_id,
                "active_sku_id": sku_id,
                "visible_sku_ids": [sku_id],
                "forbidden_sku_ids": [],
                **continuity,
                "panels": projected_panels,
                "source_shot_id": source_shot.get("shot_id"),
            }
            if prior_continuity is not None and prior_continuity != continuity:
                projected_shot["continuity_transition"] = {
                    "approval_status": "APPROVED",
                    "approval_basis": "validated_storyboard_artifact",
                    "source_storyboard_id": source.get("storyboard_id"),
                    "changes": {
                        key: {"from": prior_continuity.get(key), "to": continuity.get(key)}
                        for key in continuity
                        if prior_continuity.get(key) != continuity.get(key)
                    },
                }
            prior_continuity = continuity
            shots.append(projected_shot)
            shot_index += 1
            current_ms = end_ms

    projected = {
        "workflow_profile": "storyboard_artifact",
        "workflow_profile_rules": {"storyboard_artifact": {"min_shots": shot_count, "max_shots": shot_count}},
        "total_duration_ms": total_duration_ms,
        "product_scope": {
            "mode": "single_sku",
            "active_product_id": product_id,
            "active_sku_id": sku_id,
            "allowed_sku_ids": [sku_id],
        },
        "beats": beats,
        "shots": shots,
    }
    return thaw_json(freeze_json(projected))


def validate_structured_storyboard(
    plan: Mapping[str, Any],
    task_spec_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and return an isolated JSON projection of the frozen plan contract."""

    snapshot = thaw_json(freeze_json(_object(plan, "structured_plan")))
    task_snapshot = _object(task_spec_payload, "task_spec", "STORYBOARD_CONTEXT_INVALID")
    beats = [_object(item, f"beats[{index}]", "STORYBOARD_HIERARCHY_INVALID") for index, item in enumerate(_array(snapshot.get("beats"), "beats", "STORYBOARD_HIERARCHY_INVALID"))]
    shots = [_object(item, f"shots[{index}]", "STORYBOARD_HIERARCHY_INVALID") for index, item in enumerate(_array(snapshot.get("shots"), "shots", "STORYBOARD_HIERARCHY_INVALID"))]
    if not beats or not shots:
        _fail("STORYBOARD_HIERARCHY_INVALID", "Storyboard requires Beats and Shots", "beats", "shots")
    _validate_profile(snapshot, len(shots))
    scope = _validate_scope(snapshot, task_snapshot)

    beat_ids: list[str] = []
    beat_members: dict[str, list[str]] = {}
    for index, beat in enumerate(beats, 1):
        path = f"beats[{index - 1}]"
        expected_id = f"B{index:02d}"
        if beat.get("beat_id") != expected_id or beat.get("beat_sequence") != index:
            _fail("STORYBOARD_SEQUENCE_INVALID", "Beat IDs and sequences must be contiguous", f"{path}.beat_id", f"{path}.beat_sequence")
        if any(key in beat for key in ("start_ms", "end_ms", "duration_ms")):
            _fail("STORYBOARD_HIERARCHY_INVALID", "Beat timing must be derived from its Shots", path)
        members = _string_array(beat.get("shot_ids"), f"{path}.shot_ids", "STORYBOARD_HIERARCHY_INVALID")
        if not members:
            _fail("STORYBOARD_HIERARCHY_INVALID", "Every Beat must own at least one Shot", f"{path}.shot_ids")
        beat_ids.append(expected_id)
        beat_members[expected_id] = members

    expected_start = 0
    total_duration = 0
    panel_ids: set[str] = set()
    previous_continuity: dict[str, Any] | None = None
    for index, shot in enumerate(shots, 1):
        path = f"shots[{index - 1}]"
        expected_id = f"S{index:02d}"
        if shot.get("shot_id") != expected_id or shot.get("shot_sequence") != index:
            _fail("STORYBOARD_SEQUENCE_INVALID", "Shot IDs and sequences must be contiguous", f"{path}.shot_id", f"{path}.shot_sequence")
        beat_id = shot.get("beat_id")
        if beat_id not in beat_members or expected_id not in beat_members[beat_id]:
            _fail("STORYBOARD_HIERARCHY_INVALID", "Every Shot must belong to exactly one declared Beat", f"{path}.beat_id")
        if sum(expected_id in members for members in beat_members.values()) != 1:
            _fail("STORYBOARD_HIERARCHY_INVALID", "A Shot cannot belong to multiple Beats", f"{path}.beat_id", "beats")
        missing = [field for field in SHOT_REQUIRED_FIELDS if field not in shot]
        if missing:
            _fail("STORYBOARD_SHOT_FIELDS_MISSING", "Shot is missing required execution semantics", *(f"{path}.{field}" for field in missing))
        for field in SHOT_REQUIRED_FIELDS:
            value = shot[field]
            if field in {"required_assets", "forbidden_assets"}:
                _string_array(value, f"{path}.{field}", "STORYBOARD_SHOT_FIELDS_MISSING")
            elif field == "transition":
                continue
            elif not isinstance(value, (Mapping, Sequence)) or isinstance(value, str):
                _text(value, f"{path}.{field}", "STORYBOARD_SHOT_FIELDS_MISSING")
        missing_continuity = [field for field in PRODUCT_CONTINUITY_FIELDS if field not in shot]
        if missing_continuity:
            _fail("STORYBOARD_CONTINUITY_INVALID", "Shot is missing product continuity semantics", *(f"{path}.{field}" for field in missing_continuity))
        start = _integer(shot.get("start_ms"), f"{path}.start_ms", "STORYBOARD_DURATION_MISMATCH")
        end = _integer(shot.get("end_ms"), f"{path}.end_ms", "STORYBOARD_DURATION_MISMATCH")
        duration = _integer(shot.get("duration_ms"), f"{path}.duration_ms", "STORYBOARD_DURATION_MISMATCH")
        if start != expected_start or end <= start or end - start != duration:
            _fail("STORYBOARD_DURATION_MISMATCH", "Shot timeline must be contiguous and internally consistent", f"{path}.start_ms", f"{path}.end_ms", f"{path}.duration_ms")
        expected_start = end
        total_duration += duration
        _validate_transition(shot, path, duration)
        _validate_motion(shot, path)
        visible = _string_array(shot["visible_sku_ids"], f"{path}.visible_sku_ids", "STORYBOARD_PRODUCT_SCOPE_INVALID")
        forbidden = _string_array(shot["forbidden_sku_ids"], f"{path}.forbidden_sku_ids", "STORYBOARD_PRODUCT_SCOPE_INVALID")
        if shot["active_product_id"] != scope["active_product_id"] or shot["active_sku_id"] not in scope["allowed_sku_ids"]:
            _fail("STORYBOARD_PRODUCT_SCOPE_INVALID", "Shot active Product/SKU conflicts with the declared scope", f"{path}.active_product_id", f"{path}.active_sku_id")
        if set(visible) - set(scope["allowed_sku_ids"]) or set(visible) & set(forbidden):
            _fail("STORYBOARD_PRODUCT_SCOPE_INVALID", "Visible SKU values violate the declared scope", f"{path}.visible_sku_ids", f"{path}.forbidden_sku_ids")
        if scope["mode"] == "single_sku" and any(item != scope["active_sku_id"] for item in visible):
            _fail("STORYBOARD_SKU_SCOPE_UNAUTHORIZED", "Single-SKU storyboard contains another SKU", f"{path}.visible_sku_ids")
        current_continuity = {field: shot.get(field) for field in ("active_product_id", "active_sku_id", "product_state", "package_state", "container_state", "scale_constraints", "character_state", "wardrobe_state", "scene_state")}
        if previous_continuity is not None and current_continuity != previous_continuity:
            declaration = shot.get("continuity_transition")
            if not isinstance(declaration, Mapping) or declaration.get("approval_status") != "APPROVED":
                changed = [field for field, value in current_continuity.items() if previous_continuity.get(field) != value]
                _fail("STORYBOARD_CONTINUITY_INVALID", "Cross-Shot continuity change lacks explicit approval", *(f"{path}.{field}" for field in changed))
        previous_continuity = current_continuity
        validated_panels = _validate_panels(shot, path)
        for panel in validated_panels:
            if panel["panel_id"] in panel_ids:
                _fail("STORYBOARD_SEQUENCE_INVALID", "Panel IDs must be globally unique", f"{path}.panels")
            panel_ids.add(panel["panel_id"])
        shot["panels"] = validated_panels

    declared_total = _integer(snapshot.get("total_duration_ms"), "total_duration_ms", "STORYBOARD_DURATION_MISMATCH")
    if total_duration != declared_total or expected_start != declared_total:
        _fail("STORYBOARD_DURATION_MISMATCH", "Shot durations and final end time must equal total duration", "total_duration_ms", "shots")

    flattened_members = [shot_id for beat_id in beat_ids for shot_id in beat_members[beat_id]]
    if flattened_members != [shot["shot_id"] for shot in shots]:
        _fail("STORYBOARD_HIERARCHY_INVALID", "Beat Shot spans must be ordered and contiguous", "beats", "shots")
    by_id = {shot["shot_id"]: shot for shot in shots}
    derived_beats = []
    for beat in beats:
        members = beat_members[beat["beat_id"]]
        first, last = by_id[members[0]], by_id[members[-1]]
        derived_beats.append({**beat, "start_ms": first["start_ms"], "end_ms": last["end_ms"], "duration_ms": last["end_ms"] - first["start_ms"]})
    snapshot["product_scope"] = scope
    snapshot["beats"] = derived_beats
    snapshot["shots"] = shots
    return thaw_json(freeze_json(snapshot))
