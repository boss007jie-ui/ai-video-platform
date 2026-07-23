"""Deterministic Story/Scene/Beat/Shot/Panel rules for Storyboard."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .interface import StoryboardError, safe_field_segment


def _items(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or not value:
        raise StoryboardError(
            "STORYBOARD_PLAN_INCOMPLETE",
            "validation",
            "Storyboard hierarchy requires at least one item at every level",
            field_paths=(path,),
        )
    return value


def _required_text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StoryboardError(
            "STORYBOARD_PLAN_INCOMPLETE",
            "validation",
            "Storyboard identifiers and text fields must be non-empty strings",
            field_paths=(path,),
        )
    return value.strip()


def validate_story(
    story: Mapping[str, Any],
    *,
    product_id: str,
    visual_constraints: Mapping[str, Any],
) -> None:
    if not isinstance(story, Mapping):
        raise StoryboardError(
            "STORYBOARD_PLAN_INCOMPLETE",
            "validation",
            "Storyboard plan must be an object",
            field_paths=("plan",),
        )
    _required_text(story.get("title"), "plan.title")
    if story.get("product_id") != product_id:
        raise StoryboardError(
            "STORYBOARD_PRODUCT_MISMATCH",
            "conflict",
            "Storyboard product identity does not match ProductContextBundle",
            field_paths=("plan.product_id",),
        )

    seen: dict[str, set[str]] = {name: set() for name in ("scene", "beat", "shot", "panel")}
    last_emotion: float | None = None
    previous_continuity: dict[str, Any] = {}

    for scene_index, scene in enumerate(_items(story.get("scenes"), "plan.scenes")):
        scene_path = f"plan.scenes[{scene_index}]"
        if not isinstance(scene, Mapping):
            raise StoryboardError("STORYBOARD_PLAN_INCOMPLETE", "validation", "Scene must be an object", field_paths=(scene_path,))
        _unique_id(scene, "scene_id", "scene", scene_path, seen)
        score = scene.get("emotion_score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
            raise StoryboardError(
                "STORYBOARD_EMOTIONAL_PROGRESSION_INVALID",
                "validation",
                "Scene emotion_score must be between 0 and 100",
                field_paths=(f"{scene_path}.emotion_score",),
            )
        if last_emotion is not None and score < last_emotion:
            raise StoryboardError(
                "STORYBOARD_EMOTIONAL_PROGRESSION_INVALID",
                "conflict",
                "Scene emotional progression must not regress",
                field_paths=(f"{scene_path}.emotion_score",),
            )
        last_emotion = float(score)
        _required_text(scene.get("emotion"), f"{scene_path}.emotion")
        _required_text(scene.get("setting"), f"{scene_path}.setting")

        for beat_index, beat in enumerate(_items(scene.get("beats"), f"{scene_path}.beats")):
            beat_path = f"{scene_path}.beats[{beat_index}]"
            if not isinstance(beat, Mapping):
                raise StoryboardError("STORYBOARD_PLAN_INCOMPLETE", "validation", "Beat must be an object", field_paths=(beat_path,))
            _unique_id(beat, "beat_id", "beat", beat_path, seen)
            _required_text(beat.get("action"), f"{beat_path}.action")

            for shot_index, shot in enumerate(_items(beat.get("shots"), f"{beat_path}.shots")):
                shot_path = f"{beat_path}.shots[{shot_index}]"
                if not isinstance(shot, Mapping):
                    raise StoryboardError("STORYBOARD_PLAN_INCOMPLETE", "validation", "Shot must be an object", field_paths=(shot_path,))
                _unique_id(shot, "shot_id", "shot", shot_path, seen)
                _required_text(shot.get("framing"), f"{shot_path}.framing")

                for panel_index, panel in enumerate(_items(shot.get("panels"), f"{shot_path}.panels")):
                    panel_path = f"{shot_path}.panels[{panel_index}]"
                    if not isinstance(panel, Mapping):
                        raise StoryboardError("STORYBOARD_PLAN_INCOMPLETE", "validation", "Panel must be an object", field_paths=(panel_path,))
                    _unique_id(panel, "panel_id", "panel", panel_path, seen)
                    prompt = _required_text(panel.get("prompt"), f"{panel_path}.prompt")
                    if panel.get("product_id") != product_id:
                        raise StoryboardError(
                            "STORYBOARD_PRODUCT_MISMATCH",
                            "conflict",
                            "Every product Panel must retain the confirmed product identity",
                            field_paths=(f"{panel_path}.product_id",),
                        )
                    _validate_product_constraints(prompt, visual_constraints, panel_path)
                    continuity = panel.get("continuity")
                    if not isinstance(continuity, Mapping) or not continuity:
                        raise StoryboardError(
                            "STORYBOARD_PLAN_INCOMPLETE",
                            "validation",
                            "Every Panel requires explicit continuity state",
                            field_paths=(f"{panel_path}.continuity",),
                        )
                    _validate_transition(previous_continuity, continuity, panel.get("continuity_changes", {}), panel_path)
                    previous_continuity = dict(continuity)

    from .planning import validate_panel_entity_references

    validate_panel_entity_references(story, product_id=product_id)


def _unique_id(
    item: Mapping[str, Any],
    field_name: str,
    kind: str,
    path: str,
    seen: dict[str, set[str]],
) -> None:
    value = _required_text(item.get(field_name), f"{path}.{field_name}")
    if value in seen[kind]:
        raise StoryboardError(
            "STORYBOARD_ID_DUPLICATE",
            "conflict",
            f"Duplicate {kind} identity is not allowed",
            field_paths=(f"{path}.{field_name}",),
        )
    seen[kind].add(value)


def _validate_product_constraints(prompt: str, constraints: Mapping[str, Any], panel_path: str) -> None:
    normalized = prompt.casefold()
    for name in ("required_color", "logo_visibility"):
        value = constraints.get(name)
        if isinstance(value, str) and value.strip() and value.casefold() not in normalized:
            raise StoryboardError(
                "STORYBOARD_PRODUCT_CONSTRAINT_VIOLATION",
                "conflict",
                "Panel prompt does not preserve a confirmed visual product constraint",
                field_paths=(f"{panel_path}.prompt",),
                details={"constraint": name},
            )


def _validate_transition(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    changes: object,
    panel_path: str,
) -> None:
    if not isinstance(changes, Mapping):
        raise StoryboardError(
            "STORYBOARD_CONTINUITY_CONFLICT",
            "validation",
            "continuity_changes must be an object",
            field_paths=(f"{panel_path}.continuity_changes",),
        )
    for key, prior_value in previous.items():
        current_value = current.get(key)
        if current_value == prior_value:
            continue
        declaration = changes.get(key)
        field_path = f"{panel_path}.continuity.{safe_field_segment(key)}"
        if not isinstance(declaration, Mapping):
            raise StoryboardError(
                "STORYBOARD_CONTINUITY_CONFLICT",
                "conflict",
                "Continuity state changed without an explicit transition",
                field_paths=(field_path,),
            )
        if (
            declaration.get("from") != prior_value
            or declaration.get("to") != current_value
            or not isinstance(declaration.get("reason"), str)
            or not declaration["reason"].strip()
        ):
            raise StoryboardError(
                "STORYBOARD_CONTINUITY_CONFLICT",
                "conflict",
                "Continuity transition must record exact from/to values and a reason",
                field_paths=(field_path,),
            )
