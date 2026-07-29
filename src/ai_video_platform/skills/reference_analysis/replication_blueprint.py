"""Owner-local replication profiles, evidence normalization, and blueprint derivation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib

from .errors import ErrorCode, SkillError


PROFILE_CAPABILITIES = {
    "MOTION_REPLICATION": frozenset({"motion", "scene"}),
    "NARRATIVE_REPLICATION": frozenset({"narrative"}),
    "HYBRID_REPLICATION": frozenset({"motion", "narrative", "scene"}),
}
ANALYSIS_PROFILES = frozenset(PROFILE_CAPABILITIES)
DEFAULT_ANALYSIS_PROFILE = "HYBRID_REPLICATION"

ACTION_STATES = {
    "ACTION_START",
    "ACTION_ONSET",
    "PRE_CONTACT",
    "FIRST_CONTACT",
    "CONTROL_OR_GRIP",
    "ACTION_APEX",
    "RELEASE_OR_REVERSAL",
    "ACTION_END",
    "FINAL_HOLD",
}

CONTACT_STATES = {
    "NO_CONTACT",
    "APPROACHING",
    "PRE_CONTACT",
    "FIRST_CONTACT",
    "GRIPPING",
    "HOLDING",
    "MANIPULATING",
    "RELEASING",
    "SEPARATED",
}

NARRATIVE_ROLES = {
    "SETUP",
    "INCITING_EVENT",
    "ESCALATION",
    "INFORMATION_CHANGE",
    "DECISION",
    "TURNING_POINT",
    "REVEAL",
    "REACTION",
    "PRODUCT_PROOF",
    "CONSEQUENCE",
    "RESOLUTION",
    "CTA",
    "NATURAL_CLOSE",
}

_ACTION_KEYS = {
    "action_id",
    "actor",
    "body_part",
    "start_pose",
    "end_pose",
    "motion_direction",
    "motion_path",
    "motion_speed",
    "joint_or_limb_change",
    "hand_state",
    "object_state_before",
    "object_state_after",
    "camera_motion",
    "states",
}
_STATE_KEYS = {"state", "timestamp_ms", "contact_state"}
_FACT_KEYS = {
    "fact_id",
    "start_ms",
    "end_ms",
    "actor",
    "action",
    "object",
    "location",
    "start_state",
    "end_state",
    "trigger",
    "result",
    "information_revealed",
    "spoken_text",
    "subtitle_text",
}
_CONTEXT_KEYS = {"start_ms", "end_ms", "shot_id", "scene_id"}
SCENE_FIELDS = (
    "scene_type",
    "camera_position",
    "camera_height",
    "camera_direction",
    "framing",
    "large_object_layout",
    "subject_position",
    "subject_scale_in_frame",
    "subject_orientation",
    "entry_direction",
    "exit_direction",
    "movement_route",
    "light_direction",
    "major_spatial_relationships",
)
_SCENE_KEYS = {"scene_id", "start_ms", "end_ms", *SCENE_FIELDS}


def profile_supports(profile: str, capability: str) -> bool:
    return capability in PROFILE_CAPABILITIES.get(profile, frozenset())


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Replication evidence must be an object", field_paths=(field,))
    return {str(key): nested for key, nested in value.items()}


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Replication evidence text is invalid", field_paths=(field,))
    return value.strip()


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Replication evidence timestamp is invalid", field_paths=(field,))
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        paths = [*(f"{field}.{key}" for key in sorted(expected - set(value))), *(f"{field}.{key}" for key in sorted(set(value) - expected))]
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "Replication evidence fields are invalid",
            field_paths=tuple(paths) or (field,),
        )


def normalize_replication_inputs(value: Mapping[str, object], duration_ms: int) -> dict[str, list[dict[str, object]]]:
    """Validate fake/owner-local multimodal evidence without inventing missing facts."""
    result: dict[str, list[dict[str, object]]] = {
        "segment_contexts": [],
        "motion_actions": [],
        "narrative_facts": [],
        "scene_annotations": [],
    }
    contexts = value.get("segment_contexts", [])
    actions = value.get("motion_actions", [])
    facts = value.get("narrative_facts", [])
    scenes = value.get("scene_annotations", [])
    if not all(isinstance(items, list) for items in (contexts, actions, facts, scenes)):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Replication evidence collections must be arrays")

    for index, raw in enumerate(contexts):
        field = f"offline_analysis.segment_contexts[{index}]"
        context = _mapping(raw, field)
        _exact_keys(context, _CONTEXT_KEYS, field)
        start_ms = _integer(context["start_ms"], f"{field}.start_ms")
        end_ms = _integer(context["end_ms"], f"{field}.end_ms", minimum=1)
        if end_ms <= start_ms or end_ms > duration_ms:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Segment context interval is invalid", field_paths=(field,))
        result["segment_contexts"].append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "shot_id": _text(context["shot_id"], f"{field}.shot_id"),
            "scene_id": _text(context["scene_id"], f"{field}.scene_id"),
        })

    seen_actions: set[str] = set()
    for index, raw in enumerate(actions):
        field = f"offline_analysis.motion_actions[{index}]"
        action = _mapping(raw, field)
        _exact_keys(action, _ACTION_KEYS, field)
        action_id = _text(action["action_id"], f"{field}.action_id")
        if action_id in seen_actions:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Motion action IDs must be unique", field_paths=(f"{field}.action_id",))
        seen_actions.add(action_id)
        raw_states = action["states"]
        if not isinstance(raw_states, list) or len(raw_states) < 2:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Motion action requires at least two evidenced states", field_paths=(f"{field}.states",))
        states: list[dict[str, object]] = []
        prior_timestamp = -1
        seen_state_names: set[str] = set()
        for state_index, raw_state in enumerate(raw_states):
            state_field = f"{field}.states[{state_index}]"
            state = _mapping(raw_state, state_field)
            _exact_keys(state, _STATE_KEYS, state_field)
            state_name = _text(state["state"], f"{state_field}.state")
            contact_state = _text(state["contact_state"], f"{state_field}.contact_state")
            timestamp_ms = _integer(state["timestamp_ms"], f"{state_field}.timestamp_ms")
            if state_name not in ACTION_STATES or contact_state not in CONTACT_STATES:
                raise SkillError(ErrorCode.VALIDATION_FAILED, "Motion or contact state is unsupported", field_paths=(state_field,))
            if timestamp_ms <= prior_timestamp or timestamp_ms >= duration_ms or state_name in seen_state_names:
                raise SkillError(ErrorCode.VALIDATION_FAILED, "Motion states must be unique and time ordered", field_paths=(state_field,))
            prior_timestamp = timestamp_ms
            seen_state_names.add(state_name)
            states.append({"state": state_name, "timestamp_ms": timestamp_ms, "contact_state": contact_state})
        result["motion_actions"].append({
            **{key: _text(action[key], f"{field}.{key}") for key in _ACTION_KEYS - {"states"}},
            "states": states,
        })

    seen_facts: set[str] = set()
    for index, raw in enumerate(facts):
        field = f"offline_analysis.narrative_facts[{index}]"
        fact = _mapping(raw, field)
        _exact_keys(fact, _FACT_KEYS, field)
        fact_id = _text(fact["fact_id"], f"{field}.fact_id")
        start_ms = _integer(fact["start_ms"], f"{field}.start_ms")
        end_ms = _integer(fact["end_ms"], f"{field}.end_ms", minimum=1)
        if fact_id in seen_facts or end_ms <= start_ms or end_ms > duration_ms:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Narrative fact identity or interval is invalid", field_paths=(field,))
        seen_facts.add(fact_id)
        result["narrative_facts"].append({
            **{key: _text(fact[key], f"{field}.{key}") for key in _FACT_KEYS - {"start_ms", "end_ms"}},
            "start_ms": start_ms,
            "end_ms": end_ms,
        })

    seen_scenes: set[str] = set()
    for index, raw in enumerate(scenes):
        field = f"offline_analysis.scene_annotations[{index}]"
        scene = _mapping(raw, field)
        _exact_keys(scene, _SCENE_KEYS, field)
        scene_id = _text(scene["scene_id"], f"{field}.scene_id")
        start_ms = _integer(scene["start_ms"], f"{field}.start_ms")
        end_ms = _integer(scene["end_ms"], f"{field}.end_ms", minimum=1)
        if scene_id in seen_scenes or end_ms <= start_ms or end_ms > duration_ms:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Scene annotation identity or interval is invalid", field_paths=(field,))
        seen_scenes.add(scene_id)
        result["scene_annotations"].append({
            "scene_id": scene_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            **{name: _text(scene[name], f"{field}.{name}") for name in SCENE_FIELDS},
        })
    return result


def apply_segment_contexts(
    segments: Sequence[Mapping[str, object]],
    contexts: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_interval = {(int(item["start_ms"]), int(item["end_ms"])): item for item in contexts}
    enriched: list[dict[str, object]] = []
    for index, segment in enumerate(segments):
        interval = (int(segment["start_ms"]), int(segment["end_ms"]))
        context = by_interval.get(interval)
        enriched.append({
            **dict(segment),
            "shot_id": str(context["shot_id"]) if context is not None else f"shot-{index + 1:03d}",
            "scene_id": str(context["scene_id"]) if context is not None else "scene-unavailable",
        })
    if contexts and len(by_interval) != len(segments):
        raise SkillError(
            ErrorCode.EVIDENCE_MISSING,
            "Segment contexts must cover every fine segment exactly",
            field_paths=("offline_analysis.segment_contexts",),
        )
    return enriched


def _owning_segment(segments: Sequence[Mapping[str, object]], timestamp_ms: int) -> Mapping[str, object]:
    for segment in segments:
        if int(segment["start_ms"]) <= timestamp_ms < int(segment["end_ms"]):
            return segment
    raise SkillError(ErrorCode.EVIDENCE_MISSING, "Semantic keyframe timestamp has no owning fine segment")


def _add_frame_request(
    requests: dict[tuple[str, int], dict[str, object]],
    segment: Mapping[str, object],
    timestamp_ms: int,
    *,
    frame_role: str = "semantic",
    action_roles: Sequence[str] = (),
    narrative_roles: Sequence[str] = (),
) -> None:
    key = (str(segment["segment_id"]), timestamp_ms)
    request = requests.setdefault(key, {
        "segment_id": segment["segment_id"],
        "shot_id": segment["shot_id"],
        "scene_id": segment["scene_id"],
        "timestamp_ms": timestamp_ms,
        "frame_role": frame_role,
        "action_roles": [],
        "narrative_roles": [],
    })
    if request["frame_role"] == "semantic" and frame_role != "semantic":
        request["frame_role"] = frame_role
    for name, roles in (("action_roles", action_roles), ("narrative_roles", narrative_roles)):
        for role in roles:
            if role not in request[name]:  # type: ignore[operator]
                request[name].append(role)  # type: ignore[union-attr]


def plan_keyframe_requests(
    segments: Sequence[Mapping[str, object]],
    profile: str,
    motion_actions: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Select base frames and the first-pass motion states before coverage."""
    if profile not in ANALYSIS_PROFILES:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "analysis_profile is unsupported")
    requests: dict[tuple[str, int], dict[str, object]] = {}

    for segment in segments:
        start_ms = int(segment["start_ms"])
        end_ms = int(segment["end_ms"])
        end_margin = min(100, max(1, (end_ms - start_ms) // 4))
        _add_frame_request(requests, segment, start_ms, frame_role="start")
        _add_frame_request(requests, segment, start_ms + ((end_ms - start_ms) // 2), frame_role="representative")
        _add_frame_request(requests, segment, end_ms - end_margin, frame_role="end")

    if profile_supports(profile, "motion"):
        initial_states = {"ACTION_START", "ACTION_APEX", "ACTION_END", "FINAL_HOLD"}
        for action in motion_actions:
            states = action["states"]  # type: ignore[assignment]
            for state_index, state in enumerate(states):
                timestamp_ms = int(state["timestamp_ms"])
                role = str(state["state"])
                if role in initial_states or state_index in {0, len(states) - 1}:
                    _add_frame_request(
                        requests,
                        _owning_segment(segments, timestamp_ms),
                        timestamp_ms,
                        action_roles=(role,),
                    )

    ordered = sorted(requests.values(), key=lambda item: (int(item["timestamp_ms"]), str(item["segment_id"])))
    return ordered


def _narrative_groups(
    facts: Sequence[Mapping[str, object]],
    segments: Sequence[Mapping[str, object]],
    analyses: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    analysis_by_segment = {str(item["segment_id"]): item for item in analyses}
    groups: list[dict[str, object]] = []
    for fact in sorted(facts, key=lambda item: (int(item["start_ms"]), str(item["fact_id"]))):
        midpoint = int(fact["start_ms"]) + ((int(fact["end_ms"]) - int(fact["start_ms"])) // 2)
        segment = _owning_segment(segments, midpoint)
        segment_id = str(segment["segment_id"])
        analysis = analysis_by_segment.get(segment_id)
        if analysis is None:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Narrative fact has no analyzed source segment")
        stage_title = str(analysis["stage_title"])
        if not groups or groups[-1]["stage_title"] != stage_title:
            groups.append({
                "event_id": f"event-{len(groups) + 1:03d}",
                "stage_title": stage_title,
                "facts": [],
                "source_segments": [],
            })
        groups[-1]["facts"].append(fact)  # type: ignore[union-attr]
        if segment_id not in groups[-1]["source_segments"]:  # type: ignore[operator]
            groups[-1]["source_segments"].append(segment_id)  # type: ignore[union-attr]
    return groups


def _derived_event_roles(group: Mapping[str, object], index: int, count: int) -> list[str]:
    facts = group["facts"]  # type: ignore[assignment]
    title = str(group["stage_title"]).casefold()
    roles: list[str] = []
    if index == 0:
        roles.append("SETUP")
    elif index == 1:
        roles.append("INCITING_EVENT")
    elif index < count - 1:
        roles.append("ESCALATION")
    if any(str(fact["information_revealed"]) != "UNAVAILABLE" for fact in facts):
        roles.extend(("INFORMATION_CHANGE", "REVEAL"))
    if any(token in title for token in ("demo", "proof", "result", "reveal")):
        roles.append("PRODUCT_PROOF")
    if index == count - 1:
        roles.append("NATURAL_CLOSE")
    return list(dict.fromkeys(roles or ["INFORMATION_CHANGE"]))


def plan_coverage_keyframe_requests(
    segments: Sequence[Mapping[str, object]],
    profile: str,
    motion_actions: Sequence[Mapping[str, object]],
    narrative_facts: Sequence[Mapping[str, object]],
    segment_analysis: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, object]]]]:
    """Check adjacent first-pass evidence and request one bounded supplementation pass."""
    requests: dict[tuple[str, int], dict[str, object]] = {}

    def add(timestamp_ms: int, *, action_roles: Sequence[str] = (), narrative_roles: Sequence[str] = ()) -> None:
        segment = _owning_segment(segments, timestamp_ms)
        _add_frame_request(
            requests,
            segment,
            timestamp_ms,
            action_roles=action_roles,
            narrative_roles=narrative_roles,
        )

    motion_added: list[dict[str, object]] = []
    motion_checks: list[dict[str, object]] = []
    if profile_supports(profile, "motion"):
        initial_states = {"ACTION_START", "ACTION_APEX", "ACTION_END", "FINAL_HOLD"}
        for action in motion_actions:
            states = action["states"]  # type: ignore[assignment]
            selected_indices = [
                index for index, state in enumerate(states)
                if state["state"] in initial_states or index in {0, len(states) - 1}
            ]
            for before_index, after_index in zip(selected_indices, selected_indices[1:]):
                before = states[before_index]
                after = states[after_index]
                missing = states[before_index + 1:after_index]
                check = {
                    "action_id": action["action_id"],
                    "from_state": before["state"],
                    "to_state": after["state"],
                    "start_ms": before["timestamp_ms"],
                    "end_ms": after["timestamp_ms"],
                    "contact_state_changed": before["contact_state"] != after["contact_state"],
                    "missing_states": [state["state"] for state in missing],
                    "supplemented": bool(missing),
                }
                motion_checks.append(check)
                for state in missing:
                    timestamp_ms = int(state["timestamp_ms"])
                    add(timestamp_ms, action_roles=(str(state["state"]),))
                    motion_added.append({
                        "action_id": action["action_id"],
                        "state": state["state"],
                        "timestamp_ms": timestamp_ms,
                        "gap_start_ms": before["timestamp_ms"],
                        "gap_end_ms": after["timestamp_ms"],
                        "reason": "adjacent_motion_keyframes_skip_an_evidenced_state",
                    })

    narrative_added: list[dict[str, object]] = []
    narrative_checks: list[dict[str, object]] = []
    narrative_gaps: list[dict[str, object]] = []
    if profile_supports(profile, "narrative"):
        groups = _narrative_groups(narrative_facts, segments, segment_analysis)
        for event_index, group in enumerate(groups):
            roles = _derived_event_roles(group, event_index, len(groups))
            facts = group["facts"]  # type: ignore[assignment]
            if not facts:
                continue
            first = facts[0]
            first_timestamp = int(first["start_ms"]) + ((int(first["end_ms"]) - int(first["start_ms"])) // 2)
            add(first_timestamp, narrative_roles=roles)
            for before, after in zip(facts, facts[1:]):
                state_continuity = before["end_state"] == after["start_state"]
                important_change = (
                    before["end_state"] != after["end_state"]
                    or after["information_revealed"] != "UNAVAILABLE"
                    or after["subtitle_text"] != "UNAVAILABLE"
                )
                timestamp_ms = int(after["start_ms"]) + ((int(after["end_ms"]) - int(after["start_ms"])) // 2)
                narrative_checks.append({
                    "event_id": group["event_id"],
                    "from_fact_id": before["fact_id"],
                    "to_fact_id": after["fact_id"],
                    "state_continuity": state_continuity,
                    "important_change": important_change,
                    "supplemented": important_change,
                })
                if important_change:
                    add(timestamp_ms, narrative_roles=roles)
                    narrative_added.append({
                        "event_id": group["event_id"],
                        "fact_id": after["fact_id"],
                        "narrative_roles": roles,
                        "timestamp_ms": timestamp_ms,
                        "reason": "adjacent_narrative_evidence_skips_an_evidenced_state_change",
                    })
        for before_group, after_group in zip(groups, groups[1:]):
            before = before_group["facts"][-1]  # type: ignore[index]
            after = after_group["facts"][0]  # type: ignore[index]
            state_continuity = before["end_state"] == after["start_state"]
            narrative_checks.append({
                "from_event_id": before_group["event_id"],
                "to_event_id": after_group["event_id"],
                "from_fact_id": before["fact_id"],
                "to_fact_id": after["fact_id"],
                "state_continuity": state_continuity,
                "supplemented": False,
            })
            if not state_continuity:
                narrative_gaps.append({
                    "from_event_id": before_group["event_id"],
                    "to_event_id": after_group["event_id"],
                    "reason": "no_source_fact_explains_the_inter_event_state_jump",
                })

    ordered = sorted(requests.values(), key=lambda item: (int(item["timestamp_ms"]), str(item["segment_id"])))
    return ordered, {
        "motion_added": motion_added,
        "motion_checks": motion_checks,
        "narrative_added": narrative_added,
        "narrative_checks": narrative_checks,
        "narrative_gaps": narrative_gaps,
    }


def _frame_lookup(keyframes: Sequence[Mapping[str, object]]) -> dict[tuple[str, int], Mapping[str, object]]:
    return {(str(frame["segment_id"]), int(frame["timestamp_ms"])): frame for frame in keyframes}


def _frame_for_timestamp(
    segments: Sequence[Mapping[str, object]],
    frames: Mapping[tuple[str, int], Mapping[str, object]],
    timestamp_ms: int,
) -> Mapping[str, object] | None:
    for segment in segments:
        if int(segment["start_ms"]) <= timestamp_ms < int(segment["end_ms"]):
            return frames.get((str(segment["segment_id"]), timestamp_ms))
    return None


def _resolve_coverage_frames(
    candidates: Sequence[Mapping[str, object]],
    segments: Sequence[Mapping[str, object]],
    lookup: Mapping[tuple[str, int], Mapping[str, object]],
) -> tuple[list[str], list[dict[str, object]]]:
    added_frame_ids: list[str] = []
    unresolved: list[dict[str, object]] = []
    for candidate in candidates:
        frame = _frame_for_timestamp(segments, lookup, int(candidate["timestamp_ms"]))
        if frame is None:
            unresolved.append(dict(candidate))
        elif str(frame["frame_id"]) not in added_frame_ids:
            added_frame_ids.append(str(frame["frame_id"]))
    return added_frame_ids, unresolved


def build_motion_artifacts(
    actions: Sequence[Mapping[str, object]],
    segments: Sequence[Mapping[str, object]],
    keyframes: Sequence[Mapping[str, object]],
    coverage_candidates: Sequence[Mapping[str, object]],
    coverage_checks: Sequence[Mapping[str, object]],
    *,
    profile: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Create action state chains, transitions, and one bounded motion coverage result."""
    if not profile_supports(profile, "motion"):
        return (
            {"analysis_profile": profile, "status": "NOT_REQUESTED", "action_chains": [], "transitions": []},
            {"motion_coverage": {"status": "NOT_REQUESTED", "iterations": 0, "initial_keyframe_count": 0, "added_frame_count": 0, "added_frame_ids": [], "checks": [], "unresolved_gaps": []}, "motion_transitions": {"transition_count": 0}},
        )
    lookup = _frame_lookup(keyframes)
    chains: list[dict[str, object]] = []
    transitions: list[dict[str, object]] = []
    added_frame_ids, unresolved = _resolve_coverage_frames(coverage_candidates, segments, lookup)
    for action in actions:
        states: list[dict[str, object]] = []
        for raw_state in action["states"]:  # type: ignore[union-attr]
            timestamp_ms = int(raw_state["timestamp_ms"])
            frame = _frame_for_timestamp(segments, lookup, timestamp_ms)
            if frame is None:
                unresolved.append({"action_id": action["action_id"], "timestamp_ms": timestamp_ms, "state": raw_state["state"]})
                continue
            states.append({
                "action_state": raw_state["state"],
                "timestamp_ms": timestamp_ms,
                "frame_id": frame["frame_id"],
                "contact_state": raw_state["contact_state"],
                "source_segment_id": frame["segment_id"],
                "source_frame_id": frame["frame_id"],
            })
        if len(states) < 2:
            continue
        source_segments = list(dict.fromkeys(str(state["source_segment_id"]) for state in states))
        source_frames = list(dict.fromkeys(str(state["source_frame_id"]) for state in states))
        chain = {
            "action_id": action["action_id"],
            "actor": action["actor"],
            "body_part": action["body_part"],
            "start_pose": action["start_pose"],
            "end_pose": action["end_pose"],
            "motion_direction": action["motion_direction"],
            "motion_path": action["motion_path"],
            "motion_speed": action["motion_speed"],
            "action_duration_ms": int(states[-1]["timestamp_ms"]) - int(states[0]["timestamp_ms"]),
            "joint_or_limb_change": action["joint_or_limb_change"],
            "hand_state": action["hand_state"],
            "object_state_before": action["object_state_before"],
            "object_state_after": action["object_state_after"],
            "camera_motion": action["camera_motion"],
            "source_segments": source_segments,
            "source_frames": source_frames,
            "states": states,
        }
        chains.append(chain)
        for before, after in zip(states, states[1:]):
            transitions.append({
                "from_frame_id": before["frame_id"],
                "to_frame_id": after["frame_id"],
                "start_ms": before["timestamp_ms"],
                "end_ms": after["timestamp_ms"],
                "duration_ms": int(after["timestamp_ms"]) - int(before["timestamp_ms"]),
                "actor": action["actor"],
                "body_part": action["body_part"],
                "motion_path": action["motion_path"],
                "direction": action["motion_direction"],
                "speed_profile": action["motion_speed"],
                "contact_state_before": before["contact_state"],
                "contact_state_during": f"{before['contact_state']} -> {after['contact_state']}",
                "contact_state_after": after["contact_state"],
                "product_motion": f"{action['object_state_before']} -> {action['object_state_after']}",
                "camera_motion": action["camera_motion"],
                "continuity_notes": "Adjacent source frames bound one continuous evidenced action interval.",
            })
    motion = {
        "analysis_profile": profile,
        "status": "PASS" if not unresolved else "INCOMPLETE",
        "action_chains": chains,
    }
    coverage = {
        "motion_coverage": {
            "status": "PASS" if actions and not unresolved else ("UNAVAILABLE" if not actions else "INCOMPLETE"),
            "iterations": 1 if actions else 0,
            "initial_keyframe_count": max(0, sum(len(action["states"]) for action in actions) - len(added_frame_ids)),
            "added_frame_count": len(added_frame_ids),
            "added_frame_ids": added_frame_ids,
            "checks": [dict(check) for check in coverage_checks],
            "unresolved_gaps": unresolved,
        },
        "motion_transitions": {"transition_count": len(transitions)},
    }
    motion["transitions"] = transitions
    return motion, coverage


def build_narrative_artifacts(
    facts: Sequence[Mapping[str, object]],
    segments: Sequence[Mapping[str, object]],
    keyframes: Sequence[Mapping[str, object]],
    segment_analysis: Sequence[Mapping[str, object]],
    coverage_candidates: Sequence[Mapping[str, object]],
    coverage_checks: Sequence[Mapping[str, object]],
    coverage_gaps: Sequence[Mapping[str, object]],
    *,
    profile: str,
    audio_available: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    """Build verified facts into events, causal order, global roles, and proof loops."""
    method = "FACTS_TO_EVENTS_TO_VERIFIED_CAUSAL_GRAPH_TO_GLOBAL_STORY"
    if not profile_supports(profile, "narrative"):
        return (
            {"analysis_profile": profile, "status": "NOT_REQUESTED", "method": method, "facts": [], "events": [], "causal_edges": [], "global_story": [], "repeated_product_proof_loops": []},
            {"narrative_coverage": {"status": "NOT_REQUESTED", "iterations": 0, "initial_keyframe_count": 0, "added_frame_count": 0, "added_frame_ids": [], "checks": [], "unresolved_gaps": []}},
        )
    lookup = _frame_lookup(keyframes)
    normalized_facts: list[dict[str, object]] = []
    added_frame_ids, unresolved = _resolve_coverage_frames(coverage_candidates, segments, lookup)
    unresolved.extend(dict(gap) for gap in coverage_gaps)
    for fact in facts:
        timestamp_ms = int(fact["start_ms"]) + ((int(fact["end_ms"]) - int(fact["start_ms"])) // 2)
        frame = _frame_for_timestamp(segments, lookup, timestamp_ms)
        if frame is None:
            unresolved.append({"fact_id": fact["fact_id"], "timestamp_ms": timestamp_ms})
            continue
        normalized_facts.append({
            **dict(fact),
            "source_segments": [frame["segment_id"]],
            "source_frames": [frame["frame_id"]],
            "audio_evidence": (
                [f"audio:{frame['segment_id']}"]
                if audio_available and fact["spoken_text"] != "UNAVAILABLE"
                else []
            ),
            "subtitle_evidence": (
                [f"frame:{frame['frame_id']}"] if fact["subtitle_text"] != "UNAVAILABLE" else []
            ),
        })
    covered_segment_ids = {
        str(segment_id)
        for fact in normalized_facts
        for segment_id in fact["source_segments"]  # type: ignore[union-attr]
    }
    for segment in segments:
        if str(segment["segment_id"]) not in covered_segment_ids:
            unresolved.append({
                "segment_id": segment["segment_id"],
                "reason": "no_verified_narrative_fact_for_source_segment",
            })

    event_groups = _narrative_groups(normalized_facts, segments, segment_analysis)
    events: list[dict[str, object]] = []
    for event_index, group in enumerate(event_groups):
        event_id = str(group["event_id"])
        event_facts = group["facts"]  # type: ignore[assignment]
        event_facts.sort(key=lambda item: int(item["start_ms"]))
        first, last = event_facts[0], event_facts[-1]
        roles = _derived_event_roles(group, event_index, len(event_groups))
        events.append({
            "event_id": event_id,
            "stage_title": group["stage_title"],
            "actor": first["actor"],
            "action": " -> ".join(str(item["action"]) for item in event_facts),
            "object": first["object"],
            "location": first["location"],
            "start_state": first["start_state"],
            "end_state": last["end_state"],
            "trigger": first["trigger"],
            "result": last["result"],
            "information_revealed": [
                item["information_revealed"]
                for item in event_facts
                if item["information_revealed"] != "UNAVAILABLE"
            ],
            "start_ms": first["start_ms"],
            "end_ms": last["end_ms"],
            "narrative_roles": roles,
            "source_segments": list(dict.fromkeys(segment for item in event_facts for segment in item["source_segments"])),
            "source_frames": list(dict.fromkeys(frame for item in event_facts for frame in item["source_frames"])),
            "audio_evidence": list(dict.fromkeys(ref for item in event_facts for ref in item["audio_evidence"])),
            "subtitle_evidence": list(dict.fromkeys(ref for item in event_facts for ref in item["subtitle_evidence"])),
        })
    causal_edges: list[dict[str, object]] = []
    for before, after in zip(events, events[1:]):
        if before["end_state"] == after["start_state"]:
            causal_edges.append({
                "from_event_id": before["event_id"],
                "to_event_id": after["event_id"],
                "relation": "VERIFIED_STATE_CONTINUITY",
                "evidence_frames": [before["source_frames"][-1], after["source_frames"][0]],  # type: ignore[index]
            })
    global_story: list[dict[str, object]] = []
    for event in events:
        for role in event["narrative_roles"]:  # type: ignore[union-attr]
            global_story.append({
                "node_id": f"story-node-{len(global_story) + 1:03d}",
                "role": role,
                "event_id": event["event_id"],
                "source_frames": event["source_frames"],
            })

    frame_by_id = {str(frame["frame_id"]): frame for frame in keyframes}
    facts_by_scene: dict[str, list[dict[str, object]]] = {}
    for fact in normalized_facts:
        frame_id = str(fact["source_frames"][0])  # type: ignore[index]
        scene_id = str(frame_by_id[frame_id]["scene_id"])
        facts_by_scene.setdefault(scene_id, []).append(fact)
    candidates: list[tuple[str, list[dict[str, object]], tuple[str, ...]]] = []
    for scene_id, scene_facts in facts_by_scene.items():
        scene_facts.sort(key=lambda item: int(item["start_ms"]))
        signature = tuple(str(item["action"]).casefold() for item in scene_facts)
        if len(signature) >= 2:
            candidates.append((scene_id, scene_facts, signature))
    repeated_signatures = {
        signature for _, _, signature in candidates
        if sum(1 for _, _, other in candidates if other == signature) >= 2
    }
    structure_ids = {
        signature: f"proof-structure-{hashlib.sha256('|'.join(signature).encode('utf-8')).hexdigest()[:12]}"
        for signature in repeated_signatures
    }
    proof_loops: list[dict[str, object]] = []
    for scene_id, loop_facts, signature in candidates:
        if signature not in repeated_signatures:
            continue
        proof_loops.append({
            "proof_loop_id": f"proof-loop-{len(proof_loops) + 1:03d}",
            "repeated_structure_id": structure_ids[signature],
            "variation_type": "SCENE_VARIATION",
            "retained_action_structure": [str(item["action"]) for item in loop_facts],
            "changed_product_or_scene_elements": [scene_id, *list(dict.fromkeys(str(item["location"]) for item in loop_facts))],
            "source_segments": list(dict.fromkeys(segment for item in loop_facts for segment in item["source_segments"])),
            "source_frames": list(dict.fromkeys(frame for item in loop_facts for frame in item["source_frames"])),
        })
    graph = {
        "analysis_profile": profile,
        "status": "PASS" if facts and not unresolved else ("UNAVAILABLE" if not facts else "INCOMPLETE"),
        "method": method,
        "facts": normalized_facts,
        "events": events,
        "causal_edges": causal_edges,
        "global_story": global_story,
        "repeated_product_proof_loops": proof_loops,
    }
    coverage = {
        "narrative_coverage": {
            "status": "PASS" if facts and not unresolved else ("UNAVAILABLE" if not facts else "INCOMPLETE"),
            "iterations": 1 if facts else 0,
            "initial_keyframe_count": len(events),
            "added_frame_count": len(added_frame_ids),
            "added_frame_ids": added_frame_ids,
            "checks": [dict(check) for check in coverage_checks],
            "unresolved_gaps": unresolved,
        }
    }
    return graph, coverage


def build_scene_blocking_and_constraints(
    scenes: Sequence[Mapping[str, object]],
    segments: Sequence[Mapping[str, object]],
    keyframes: Sequence[Mapping[str, object]],
    *,
    profile: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Preserve spatial mechanics while explicitly allowing identity and decor replacement."""
    scene_records: list[dict[str, object]] = []
    for scene in scenes:
        scene_id = str(scene["scene_id"])
        source_segments = [
            str(segment["segment_id"])
            for segment in segments
            if str(segment["scene_id"]) == scene_id
        ]
        source_frames = [
            str(frame["frame_id"])
            for frame in keyframes
            if str(frame["scene_id"]) == scene_id and frame["frame_role"] == "representative"
        ]
        scene_records.append({
            **dict(scene),
            "source_segments": source_segments,
            "source_frames": source_frames,
            "preservation": {
                "MUST_PRESERVE": [
                    "scene_type",
                    "camera_position",
                    "camera_direction",
                    "framing",
                    "large_object_layout",
                    "subject_position",
                    "subject_scale_in_frame",
                    "subject_orientation",
                    "movement_route",
                    "major_spatial_relationships",
                ],
                "REPLACEABLE": [
                    "soft_furnishing_pattern",
                    "cushions",
                    "wall_decor",
                    "lamps",
                    "background_props",
                    "small_furniture",
                    "decorative_colors",
                ],
                "CONDITIONALLY_REPLACEABLE": [
                    "camera_height",
                    "light_direction",
                    "large_object_style",
                    "window_position",
                ],
            },
        })
    scene_map = {
        "analysis_profile": profile,
        "status": "PASS" if scenes else "UNAVAILABLE",
        "scenes": scene_records,
    }
    constraints = {
        "analysis_profile": profile,
        "person": {
            "MUST_PRESERVE": ["body_type", "body_proportions", "motion_path", "scale_in_frame", "spatial_route"],
            "REPLACEABLE": ["face_identity", "hair_style", "nonfunctional_clothing_details"],
            "CONDITIONALLY_REPLACEABLE": ["wardrobe_style", "minor_pose_styling"],
        },
        "product": {
            "MUST_PRESERVE": ["category", "silhouette", "contact_method", "action_scale_relationship", "verified_product_facts"],
            "REPLACEABLE": ["pattern", "color", "brand_identity", "protected_identity"],
            "CONDITIONALLY_REPLACEABLE": ["minor_material_finish", "nonfunctional_detail"],
        },
        "scene": {
            "MUST_PRESERVE": ["scene_category", "large_object_relationships", "subject_position", "camera_direction", "movement_route"],
            "REPLACEABLE": ["soft_furnishings", "decor", "background_props", "color_palette"],
            "CONDITIONALLY_REPLACEABLE": ["large_object_style", "camera_height", "light_style", "window_position"],
        },
        "identity_restrictions": {
            "reference_identity_must_not_be_copied": True,
            "reference_brand_must_not_be_copied": True,
            "protected_material_must_not_be_copied": True,
            "product_facts_must_remain_accurate": True,
        },
        "source_scene_ids": [str(scene["scene_id"]) for scene in scenes],
    }
    return scene_map, constraints


def enrich_segment_analysis(
    analyses: Sequence[Mapping[str, object]],
    motion: Mapping[str, object],
    narrative: Mapping[str, object],
) -> list[dict[str, object]]:
    """Attach source-bound facts and action states to their exact fine segments."""
    facts = narrative.get("facts", [])
    chains = motion.get("action_chains", [])
    enriched: list[dict[str, object]] = []
    for analysis in analyses:
        segment_id = str(analysis["segment_id"])
        segment_facts = [
            fact for fact in facts  # type: ignore[union-attr]
            if segment_id in fact["source_segments"]
        ]
        motion_evidence: list[dict[str, object]] = []
        for chain in chains:  # type: ignore[union-attr]
            states = [state for state in chain["states"] if state["source_segment_id"] == segment_id]
            if states:
                motion_evidence.append({
                    "action_id": chain["action_id"],
                    "actor": chain["actor"],
                    "body_part": chain["body_part"],
                    "states": states,
                    "source_frames": [state["frame_id"] for state in states],
                })
        enriched.append({
            **dict(analysis),
            "facts": segment_facts,
            "motion_evidence": motion_evidence,
            "audio_evidence": list(dict.fromkeys(ref for fact in segment_facts for ref in fact["audio_evidence"])),
            "subtitle_evidence": list(dict.fromkeys(ref for fact in segment_facts for ref in fact["subtitle_evidence"])),
        })
    return enriched


__all__ = [
    "ACTION_STATES",
    "ANALYSIS_PROFILES",
    "CONTACT_STATES",
    "DEFAULT_ANALYSIS_PROFILE",
    "NARRATIVE_ROLES",
    "PROFILE_CAPABILITIES",
    "SCENE_FIELDS",
    "apply_segment_contexts",
    "build_motion_artifacts",
    "build_narrative_artifacts",
    "build_scene_blocking_and_constraints",
    "enrich_segment_analysis",
    "normalize_replication_inputs",
    "plan_coverage_keyframe_requests",
    "plan_keyframe_requests",
    "profile_supports",
]
