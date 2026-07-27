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


def _motion_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("structured_definition", "description", "label"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    return ""


def _rounded(value: float) -> float:
    return round(value, 4)


def _box_center(box: Sequence[object]) -> tuple[float, float]:
    left, top, right, bottom = (float(value) for value in box)
    return _rounded((left + right) / 2), _rounded((top + bottom) / 2)


def _objects_by_id(panel: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["id"]): item
        for item in panel.get("objects", ())
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }


def _objects_of_kind(panel: Mapping[str, Any], kinds: set[str]) -> list[Mapping[str, Any]]:
    objects = [
        item
        for item in panel.get("objects", ())
        if isinstance(item, Mapping) and str(item.get("kind", "")).lower() in kinds
    ]
    return sorted(objects, key=lambda item: (_box_center(item["bbox"])[0], str(item["id"])))


def _candidate_path(
    panel: Mapping[str, Any],
    role: str,
    action: str,
    objects: Mapping[str, Mapping[str, Any]],
    used_candidates: set[int],
) -> list[list[float]] | None:
    compatible: list[tuple[float, str, tuple[tuple[float, float], ...], int, Mapping[str, Any]]] = []
    for index, candidate in enumerate(panel.get("motion_candidates", ())):
        if index in used_candidates or not isinstance(candidate, Mapping):
            continue
        if candidate.get("role") != role or candidate.get("action") != action:
            continue
        confidence = float(candidate.get("confidence", 0))
        if confidence < MIN_VISUAL_CONFIDENCE:
            continue
        subject_id = candidate.get("subject_id")
        if isinstance(subject_id, str) and subject_id not in objects:
            continue
        normalized = tuple(_point(point, "motion candidate point") for point in candidate["points"])
        compatible.append((-confidence, str(subject_id or ""), normalized, index, candidate))
    if not compatible:
        return None
    _, _, normalized, index, _ = min(compatible)
    used_candidates.add(index)
    return [[_rounded(x), _rounded(y)] for x, y in normalized]


def _press_path(panel: Mapping[str, Any], objects: Mapping[str, Mapping[str, Any]]) -> list[list[float]] | None:
    contacts = sorted(
        (item for item in panel.get("contacts", ()) if isinstance(item, Mapping)),
        key=lambda item: (str(item.get("actor_id")), str(item.get("target_id"))),
    )
    for contact in contacts:
        actor = objects.get(str(contact.get("actor_id")))
        target = objects.get(str(contact.get("target_id")))
        if not actor or not target:
            continue
        if str(actor.get("kind", "")).lower() not in {"finger", "hand", "thumb"}:
            continue
        if str(target.get("kind", "")).lower() not in {"product", "squishy"}:
            continue
        start = _box_center(actor["bbox"])
        end = _point(contact["point"], "contact point")
        return [[start[0], start[1]], [_rounded(end[0]), _rounded(end[1])]]
    return None


def _squeeze_paths(panel: Mapping[str, Any]) -> list[list[list[float]]]:
    products = _objects_of_kind(panel, {"product", "squishy"})
    hands = _objects_of_kind(panel, {"hand"})
    if not products or len(hands) < 2:
        return []
    product_box = tuple(float(value) for value in products[0]["bbox"])
    product_center_x, product_center_y = _box_center(product_box)
    left_hands = [hand for hand in hands if _box_center(hand["bbox"])[0] < product_center_x]
    right_hands = [hand for hand in hands if _box_center(hand["bbox"])[0] > product_center_x]
    if not left_hands or not right_hands:
        return []
    left = max(left_hands, key=lambda item: _box_center(item["bbox"])[0])
    right = min(right_hands, key=lambda item: _box_center(item["bbox"])[0])
    width = product_box[2] - product_box[0]
    left_box = tuple(float(value) for value in left["bbox"])
    right_box = tuple(float(value) for value in right["bbox"])
    return [
        [
            [_rounded(left_box[2]), _rounded((left_box[1] + left_box[3]) / 2)],
            [_rounded(product_center_x - width * 0.2), product_center_y],
        ],
        [
            [_rounded(right_box[0]), _rounded((right_box[1] + right_box[3]) / 2)],
            [_rounded(product_center_x + width * 0.2), product_center_y],
        ],
    ]


def _enter_path(panel: Mapping[str, Any], intent: str) -> list[list[float]] | None:
    packages = _objects_of_kind(panel, {"packaging", "package", "box", "blind_box"})
    if not packages:
        return None
    left, top, right, bottom = (float(value) for value in packages[0]["bbox"])
    center_x, center_y = _box_center((left, top, right, bottom))
    offset = (right - left) * 0.2
    if intent == "enter_left":
        start_x = min(0.98, right + offset)
    elif intent == "enter_right":
        start_x = max(0.02, left - offset)
    else:
        return None
    return [[_rounded(start_x), center_y], [center_x, center_y]]


def _camera_paths(panel: Mapping[str, Any], intent: str) -> list[list[list[float]]]:
    products = _objects_of_kind(panel, {"product", "squishy"})
    if not products:
        return []
    left, top, right, bottom = (float(value) for value in products[0]["bbox"])
    center_x, _ = _box_center((left, top, right, bottom))
    product_width = right - left
    start_y = _rounded(max(0.08, top - 0.12))
    end_y = _rounded(max(0.12, top - 0.04))
    if intent == "push":
        return [
            [[0.08, start_y], [_rounded(center_x - product_width * 0.28), end_y]],
            [[0.92, start_y], [_rounded(center_x + product_width * 0.28), end_y]],
        ]
    if intent == "pull":
        return [
            [[_rounded(center_x - product_width * 0.18), end_y], [0.08, start_y]],
            [[_rounded(center_x + product_width * 0.18), end_y], [0.92, start_y]],
        ]
    return []


def _shot_text(entry: Mapping[str, Any], shot: Mapping[str, Any]) -> str:
    subject = _motion_text(entry.get("subject_motion"))
    if subject.strip():
        return subject
    parts = [shot.get(key) for key in ("motion_path", "start_state", "middle_state", "end_state")]
    return " ".join(part for part in parts if isinstance(part, str))


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
    shots = master.get("shots")
    shot_by_id = {
        str(shot.get("shot_id")): shot
        for shot in shots
        if isinstance(shots, Sequence) and not isinstance(shots, (str, bytes, bytearray)) and isinstance(shot, Mapping)
    } if isinstance(shots, Sequence) and not isinstance(shots, (str, bytes, bytearray)) else {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("panel_id"), str):
            raise ValueError("Master Panel entries require panel_id")
        panel_id = entry["panel_id"]
        panel = observations.get(panel_id)
        result[panel_id] = []
        if not isinstance(panel, Mapping) or float(panel["confidence"]) < MIN_VISUAL_CONFIDENCE:
            continue
        objects = _objects_by_id(panel)
        used_candidates: set[int] = set()
        camera = _camera_intents(_motion_text(entry.get("camera_motion")))
        subject = _subject_intents(_shot_text(entry, shot_by_id.get(str(entry.get("shot_id")), {})))
        annotations = result[panel_id]
        for intent in camera:
            candidate = _candidate_path(panel, "camera", intent, objects, used_candidates)
            paths = [candidate] if candidate else _camera_paths(panel, intent)
            annotations.extend({"role": "camera", "points": path} for path in paths if path)
        for intent in subject:
            if intent in {"hold", "release", "lift", "exit_left", "exit_right"}:
                candidate = _candidate_path(panel, "subject", intent, objects, used_candidates)
                if candidate:
                    annotations.append({"role": "subject", "points": candidate})
                continue
            candidate = _candidate_path(panel, "subject", intent, objects, used_candidates)
            if candidate:
                annotations.append({"role": "subject", "points": candidate})
                continue
            if intent == "press":
                path = _press_path(panel, objects)
                if path:
                    annotations.append({"role": "subject", "points": path})
            elif intent == "squeeze":
                annotations.extend({"role": "subject", "points": path} for path in _squeeze_paths(panel))
            elif intent in {"enter_left", "enter_right"}:
                path = _enter_path(panel, intent)
                if path:
                    annotations.append({"role": "subject", "points": path})
    return result
