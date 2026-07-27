"""Vision-observation validation and deterministic storyboard motion planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


MIN_VISUAL_CONFIDENCE = 0.65
_CAMERA_PATTERNS = (
    (r"\b(?:push(?:-in)?|dolly in)\b", "push"),
    (r"\b(?:pull(?:-out)?|dolly out)\b", "pull"),
    (r"\bpan(?:s|ned|ning)?\s+left\b", "pan_left"),
    (r"\bpan(?:s|ned|ning)?\s+right\b", "pan_right"),
    (r"\btilt(?:s|ed|ing)?\s+up\b", "tilt_up"),
    (r"\btilt(?:s|ed|ing)?\s+down\b", "tilt_down"),
    (r"\borbit(?:s|ed|ing)?\b", "orbit"),
)
_SUBJECT_PATTERNS = (
    (r"\b(?:press(?:es|ed|ing)?|tap(?:s|ped|ping)?)\b", "press"),
    (r"\b(?:squeeze(?:s|d|ing)?|squash(?:es|ed|ing)?|compress(?:es|ed|ing)?)\b", "squeeze"),
    (r"\b(?:rotate(?:s|d|ing)?|turn(?:s|ed|ing)?)\b", "rotate"),
    (r"\b(?:lift(?:s|ed|ing)?|rise(?:s|n|ing)?|rebound(?:s|ed|ing)?)\b", "lift"),
    (r"\bhold(?:s|ing)?\b", "hold"),
    (r"\brelease(?:s|d|ing)?\b", "release"),
)


def _camera_intents(value: str) -> tuple[str, ...]:
    return _ordered_matches(value, _CAMERA_PATTERNS)


def _subject_intents(value: str) -> tuple[str, ...]:
    lowered = value.lower()
    if "no release" in lowered and re.search(r"\bhold(?:s|ing)?\b", lowered):
        return ("hold",)
    matches: list[tuple[int, str]] = []
    for pattern, intent in _SUBJECT_PATTERNS:
        for match in re.finditer(pattern, lowered):
            if intent == "release" and "no release" in lowered[max(0, match.start() - 4):match.end()]:
                continue
            matches.append((match.start(), intent))
    right_origin = re.search(r"(?:from|off-frame)\s+(?:the\s+)?right", lowered)
    left_origin = re.search(r"(?:from|off-frame)\s+(?:the\s+)?left", lowered)
    enter = re.search(r"\b(?:enter(?:s|ed|ing)?|slide(?:s|d|ing)?|push(?:es|ed|ing)?)\b", lowered)
    withdraw = re.search(r"\b(?:withdraw(?:s|n|ing)?|exit(?:s|ed|ing)?)\b", lowered)
    if enter and right_origin:
        matches.append((enter.start(), "enter_left"))
    elif enter and left_origin:
        matches.append((enter.start(), "enter_right"))
    if withdraw and right_origin:
        matches.append((withdraw.start(), "exit_right"))
    elif withdraw and left_origin:
        matches.append((withdraw.start(), "exit_left"))
    return _deduplicate_ordered(matches)


def _ordered_matches(value: str, patterns: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    lowered = value.lower()
    matches = [
        (match.start(), intent)
        for pattern, intent in patterns
        for match in re.finditer(pattern, lowered)
    ]
    return _deduplicate_ordered(matches)


def _deduplicate_ordered(matches: Sequence[tuple[int, str]]) -> tuple[str, ...]:
    ordered: list[str] = []
    for _, intent in sorted(matches, key=lambda item: (item[0], item[1])):
        if intent not in ordered:
            ordered.append(intent)
    return tuple(ordered)


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    normalized = float(value)
    if not 0 <= normalized <= 1:
        raise ValueError(f"{label} must be normalized from 0 to 1")
    return normalized


def _point(value: object, label: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or len(value) != 2:
        raise ValueError(f"{label} must be [x, y]")
    return _number(value[0], f"{label}.x"), _number(value[1], f"{label}.y")


def _bbox(value: object, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or len(value) != 4:
        raise ValueError(f"{label} bbox must be [left, top, right, bottom]")
    left, top, right, bottom = (_number(item, f"{label} bbox") for item in value)
    if left >= right or top >= bottom:
        raise ValueError(f"{label} bbox must have positive area")
    return left, top, right, bottom


def _validate_observations(observations: Mapping[str, Any]) -> None:
    if not isinstance(observations, Mapping):
        raise ValueError("panel_visual_observations must be keyed by panel_id")
    for panel_id, panel in observations.items():
        if not isinstance(panel_id, str) or not panel_id or not isinstance(panel, Mapping):
            raise ValueError("Each panel visual observation must be an object keyed by panel_id")
        _number(panel.get("confidence"), f"{panel_id}.confidence")
        objects = panel.get("objects", ())
        contacts = panel.get("contacts", ())
        candidates = panel.get("motion_candidates", ())
        for label, collection in (("objects", objects), ("contacts", contacts), ("motion_candidates", candidates)):
            if not isinstance(collection, Sequence) or isinstance(collection, (str, bytes, bytearray)):
                raise ValueError(f"{panel_id}.{label} must be a sequence")
        for index, item in enumerate(objects):
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str) or not item["id"]:
                raise ValueError(f"{panel_id}.objects[{index}] requires id")
            if not isinstance(item.get("kind"), str) or not item["kind"]:
                raise ValueError(f"{panel_id}.objects[{index}] requires kind")
            _bbox(item.get("bbox"), f"{panel_id}.objects[{index}]")
        for index, item in enumerate(contacts):
            if not isinstance(item, Mapping):
                raise ValueError(f"{panel_id}.contacts[{index}] must be an object")
            if not all(isinstance(item.get(key), str) and item[key] for key in ("actor_id", "target_id")):
                raise ValueError(f"{panel_id}.contacts[{index}] requires actor_id and target_id")
            _point(item.get("point"), f"{panel_id}.contacts[{index}].point")
        for index, item in enumerate(candidates):
            if not isinstance(item, Mapping):
                raise ValueError(f"{panel_id}.motion_candidates[{index}] must be an object")
            if item.get("role") not in {"camera", "subject"}:
                raise ValueError(f"{panel_id}.motion_candidates[{index}].role is invalid")
            if not isinstance(item.get("action"), str) or not item["action"]:
                raise ValueError(f"{panel_id}.motion_candidates[{index}] requires action")
            subject_id = item.get("subject_id")
            if subject_id is not None and (not isinstance(subject_id, str) or not subject_id):
                raise ValueError(f"{panel_id}.motion_candidates[{index}].subject_id is invalid")
            points = item.get("points")
            if not isinstance(points, Sequence) or isinstance(points, (str, bytes, bytearray)) or len(points) < 2:
                raise ValueError(f"{panel_id}.motion_candidates[{index}].points requires at least two points")
            for point_index, value in enumerate(points):
                _point(value, f"{panel_id}.motion_candidates[{index}].points[{point_index}]")
            _number(item.get("confidence"), f"{panel_id}.motion_candidates[{index}].confidence")


def plan_motion_annotations(
    master: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Plan renderer-ready paths from script semantics and Agent observations."""

    _validate_observations(observations)
    entries = master.get("master_panel_entries")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes, bytearray)):
        raise ValueError("Master requires master_panel_entries")
    result: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("panel_id"), str):
            raise ValueError("Master Panel entries require panel_id")
        panel_id = entry["panel_id"]
        panel = observations.get(panel_id)
        result[panel_id] = []
        if not isinstance(panel, Mapping) or float(panel["confidence"]) < MIN_VISUAL_CONFIDENCE:
            continue
    return result

