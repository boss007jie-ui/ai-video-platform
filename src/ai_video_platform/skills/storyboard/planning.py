"""Offline raw-script planning and typed continuity archive helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .interface import StoryboardError, safe_field_segment


MIN_PLANNED_PANELS = 6
MAX_PLANNED_PANELS = 12
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_ENTITY_TYPES = {"character", "product", "scene", "prop"}
_ENTITY_REQUIRED_FIELDS = {
    "character": ("name", "appearance", "outfit"),
    "product": ("product_id", "appearance", "orientation"),
    "scene": ("setting",),
    "prop": ("name", "state", "quantity"),
}


def _planning_error(message: str, path: str, *, details: Mapping[str, Any] | None = None) -> StoryboardError:
    return StoryboardError(
        "STORYBOARD_PLANNING_INVALID",
        "validation",
        message,
        field_paths=(path,),
        details=details,
    )


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _planning_error("Raw script fields must be non-empty strings", path)
    return value.strip()


def _entity_text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StoryboardError(
            "STORYBOARD_CONTINUITY_ENTITY_INVALID",
            "validation",
            "Continuity entity fields must be non-empty strings",
            field_paths=(path,),
        )
    return value.strip()


def _script_scenes(raw_script: str) -> list[tuple[str, list[str]]]:
    script = raw_script.strip()
    if not script:
        raise _planning_error("raw_script must contain at least one non-empty line", "plan.raw_script")

    inline_blocks = [
        block.strip()
        for block in re.split(r"(?i)(?=\bscene\s+\d+\s*:)", script)
        if block.strip()
    ]
    inline_pattern = re.compile(
        r"(?is)^scene\s+(?P<number>\d+)\s*:\s*(?P<body>.*)$"
    )
    scenes: list[tuple[str, list[str]]] = []
    if inline_blocks and all(inline_pattern.match(block) for block in inline_blocks):
        for block in inline_blocks:
            matched = inline_pattern.match(block)
            assert matched is not None
            title = f"Scene {matched.group('number')}"
            body = matched.group("body").strip()
            scenes.append((title, [body] if body else [title]))
    else:
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n+", script)
            if paragraph.strip()
        ]
        scenes = [
            (f"Scene {index:03d}", [paragraph])
            for index, paragraph in enumerate(paragraphs or [script], start=1)
        ]

    normalized: list[tuple[str, list[str]]] = []
    for title, scene_lines in scenes:
        sentences = [
            piece.strip(" -\t")
            for line in scene_lines
            for piece in _SENTENCE_SPLIT.split(line)
            if piece.strip()
        ]
        normalized.append((title, sentences or [title]))
    return normalized


def _panel_count(options: Mapping[str, Any], sentence_count: int) -> int:
    if not isinstance(options, Mapping):
        raise _planning_error("planning_options must be an object", "plan.planning_options")
    requested = options.get("panel_count", max(MIN_PLANNED_PANELS, min(MAX_PLANNED_PANELS, sentence_count * 2)))
    if isinstance(requested, bool) or not isinstance(requested, int):
        raise _planning_error("panel_count must be an integer", "plan.planning_options.panel_count")
    if not MIN_PLANNED_PANELS <= requested <= MAX_PLANNED_PANELS:
        raise _planning_error(
            "panel_count must remain within the 6-12 panel planning band",
            "plan.planning_options.panel_count",
            details={"minimum": MIN_PLANNED_PANELS, "maximum": MAX_PLANNED_PANELS},
        )
    minimum = options.get("min_panels", MIN_PLANNED_PANELS)
    maximum = options.get("max_panels", MAX_PLANNED_PANELS)
    if (
        isinstance(minimum, bool)
        or isinstance(maximum, bool)
        or not isinstance(minimum, int)
        or not isinstance(maximum, int)
        or not MIN_PLANNED_PANELS <= minimum <= maximum <= MAX_PLANNED_PANELS
        or not minimum <= requested <= maximum
    ):
        raise _planning_error("min_panels/max_panels must bound panel_count inside 6-12", "plan.planning_options")
    return requested


def _allocate(total: int, buckets: int) -> list[int]:
    values = [total // buckets] * buckets
    for index in range(total % buckets):
        values[index] += 1
    return values


def _default_archive(product_id: str, scenes: Sequence[tuple[str, list[str]]]) -> dict[str, Any]:
    product_entity_id = product_id
    entities: list[dict[str, Any]] = [
        {
            "entity_id": "character-001",
            "entity_type": "character",
            "name": "Presenter",
            "appearance": "consistent presenter",
            "outfit": "blue-jacket",
            "relationships": [{"type": "uses", "entity_id": product_entity_id}],
        },
        {
            "entity_id": product_entity_id,
            "entity_type": "product",
            "product_id": product_id,
            "sku_id": None,
            "appearance": "confirmed product",
            "orientation": "front",
            "relationships": [],
        },
        {
            "entity_id": "scene-001",
            "entity_type": "scene",
            "setting": scenes[0][0],
            "lighting": "consistent studio lighting",
            "relationships": [{"type": "features", "entity_id": "character-001"}],
        },
        {
            "entity_id": "prop-001",
            "entity_type": "prop",
            "name": "supporting prop",
            "state": "stable",
            "quantity": 1,
            "relationships": [{"type": "in_scene", "entity_id": "scene-001"}],
        },
    ]
    return {
        "archive_version": "1.0.0",
        "entities": entities,
        "by_type": {entity_type: [entity["entity_id"] for entity in entities if entity["entity_type"] == entity_type] for entity_type in sorted(_ENTITY_TYPES)},
    }


def _normalize_archive(archive: object, product_id: str) -> dict[str, Any]:
    if not isinstance(archive, Mapping):
        raise StoryboardError(
            "STORYBOARD_CONTINUITY_ENTITY_INVALID",
            "validation",
            "continuity_archive must be an object",
            field_paths=("plan.continuity_archive",),
        )
    raw_entities = archive.get("entities")
    if not isinstance(raw_entities, Sequence) or isinstance(raw_entities, (str, bytes, bytearray)):
        raise StoryboardError(
            "STORYBOARD_CONTINUITY_ENTITY_INVALID",
            "validation",
            "continuity_archive.entities must be a list",
            field_paths=("plan.continuity_archive.entities",),
        )
    entities: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_entities):
        path = f"plan.continuity_archive.entities[{index}]"
        if not isinstance(raw, Mapping):
            raise StoryboardError(
                "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                "validation",
                "Continuity entity must be an object",
                field_paths=(path,),
            )
        entity_id = _entity_text(raw.get("entity_id"), f"{path}.entity_id")
        entity_type = _entity_text(raw.get("entity_type"), f"{path}.entity_type").casefold()
        if entity_type not in _ENTITY_TYPES:
            raise StoryboardError(
                "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                "validation",
                "Continuity entity type is not supported",
                field_paths=(f"{path}.entity_type",),
            )
        if entity_id in by_id:
            raise StoryboardError(
                "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                "conflict",
                "Continuity entity identities must be unique",
                field_paths=(f"{path}.entity_id",),
            )
        normalized = dict(raw)
        normalized["entity_id"] = entity_id
        normalized["entity_type"] = entity_type
        for field in _ENTITY_REQUIRED_FIELDS[entity_type]:
            if field == "quantity":
                quantity = raw.get(field)
                if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                    raise StoryboardError(
                        "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                        "validation",
                        "Prop quantity must be a non-negative integer",
                        field_paths=(f"{path}.{field}",),
                    )
            else:
                _entity_text(raw.get(field), f"{path}.{field}")
        if entity_type == "product" and raw.get("product_id") != product_id:
            raise StoryboardError(
                "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                "conflict",
                "Product continuity entity must match the confirmed product",
                field_paths=(f"{path}.product_id",),
            )
        relationships = raw.get("relationships", [])
        if not isinstance(relationships, Sequence) or isinstance(relationships, (str, bytes, bytearray)):
            raise StoryboardError(
                "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                "validation",
                "Continuity entity relationships must be a list",
                field_paths=(f"{path}.relationships",),
            )
        normalized["relationships"] = [dict(item) if isinstance(item, Mapping) else item for item in relationships]
        entities.append(normalized)
        by_id[entity_id] = normalized

    for index, entity in enumerate(entities):
        for relation_index, relation in enumerate(entity["relationships"]):
            path = f"plan.continuity_archive.entities[{index}].relationships[{relation_index}]"
            if not isinstance(relation, Mapping) or not _entity_text(relation.get("type"), f"{path}.type"):
                raise StoryboardError(
                    "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                    "validation",
                    "Continuity relationships require a type and target",
                    field_paths=(path,),
                )
            target = _entity_text(relation.get("entity_id"), f"{path}.entity_id")
            if target not in by_id:
                raise StoryboardError(
                    "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                    "conflict",
                    "Continuity relationship target does not exist",
                    field_paths=(f"{path}.entity_id",),
                )
            if relation["type"] == "uses" and entity["entity_type"] == "character" and by_id[target]["entity_type"] != "product":
                raise StoryboardError(
                    "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                    "conflict",
                    "Character uses relationships must target a product",
                    field_paths=(path,),
                )
    return {
        "archive_version": str(archive.get("archive_version", "1.0.0")),
        "entities": entities,
        "by_type": {entity_type: [entity["entity_id"] for entity in entities if entity["entity_type"] == entity_type] for entity_type in sorted(_ENTITY_TYPES)},
    }


def validate_continuity_archive(archive: object, *, product_id: str) -> dict[str, Any]:
    """Validate and return a deterministic typed archive while retaining generic compatibility."""

    return _normalize_archive(archive, product_id)


def build_storyboard_plan(
    raw_script: str,
    *,
    product_id: str,
    visual_constraints: Mapping[str, Any] | None = None,
    planning_options: Mapping[str, Any] | None = None,
    continuity_archive: object | None = None,
) -> dict[str, Any]:
    """Convert a raw script into a bounded Story/Scene/Beat/Shot/Panel plan."""

    script = _text(raw_script, "plan.raw_script")
    if len(script.encode("utf-8")) > 1_048_576:
        raise StoryboardError(
            "STORYBOARD_BUDGET_EXCEEDED",
            "budget",
            "raw_script exceeds the 1 MiB canonical input budget",
            field_paths=("plan.raw_script",),
        )
    scenes = _script_scenes(script)
    options = {} if planning_options is None else planning_options
    total_panels = _panel_count(options, sum(len(items) for _, items in scenes))
    if len(scenes) > total_panels:
        raise _planning_error(
            "Scene count cannot exceed the requested panel capacity",
            "plan.raw_script",
            details={"scene_count": len(scenes), "panel_count": total_panels},
        )
    scene_counts = _allocate(total_panels, len(scenes))
    constraints = visual_constraints or {}
    color = str(constraints.get("required_color") or "product")
    logo = str(constraints.get("logo_visibility") or "visible")
    generated_archive = _normalize_archive(continuity_archive, product_id) if continuity_archive is not None else _default_archive(product_id, scenes)
    entity_ids = [entity["entity_id"] for entity in generated_archive["entities"]]
    story_scenes: list[dict[str, Any]] = []
    panel_number = 1
    for scene_index, ((scene_title, scene_lines), scene_panel_count) in enumerate(zip(scenes, scene_counts, strict=True), start=1):
        scene_id = f"scene-{scene_index:03d}"
        shot_counts = _allocate(scene_panel_count, max(1, (scene_panel_count + 1) // 2))
        panels_for_scene: list[dict[str, Any]] = []
        line_index = 0
        for shot_index, shot_panel_count in enumerate(shot_counts, start=1):
            panels: list[dict[str, Any]] = []
            for local_index in range(shot_panel_count):
                source_line = scene_lines[line_index % len(scene_lines)]
                line_index += 1
                panel_id = f"panel-{panel_number:03d}"
                panel_number += 1
                panels.append(
                    {
                        "panel_id": panel_id,
                        "panel_type": ("establishing" if local_index == 0 and shot_index == 1 else "detail" if local_index else "action"),
                        "layout": ("wide" if local_index == 0 else "close"),
                        "key_moment": source_line,
                        "prompt": f"{source_line}; show the {color} product with logo {logo}",
                        "product_id": product_id,
                        "continuity": {"actor_outfit": "blue-jacket", "product_orientation": "front"},
                        "continuity_entities": list(entity_ids),
                    }
                )
            panels_for_scene.append(
                {
                    "shot_id": f"shot-{scene_index:03d}-{shot_index:02d}",
                    "framing": ("wide" if shot_index == 1 else "close-up"),
                    "shot_type": ("establishing" if shot_index == 1 else "detail"),
                    "panels": panels,
                }
            )
        story_scenes.append(
            {
                "scene_id": scene_id,
                "setting": scene_title,
                "emotion": "friction" if scene_index == 1 else "confidence",
                "emotion_score": int(round(20 + (60 * (scene_index - 1) / max(1, len(scenes) - 1)))),
                "beats": [
                    {
                        "beat_id": f"beat-{scene_index:03d}",
                        "action": " ".join(scene_lines),
                        "shots": panels_for_scene,
                    }
                ],
            }
        )
    return {
        "title": scenes[0][0] or "Storyboard from raw script",
        "product_id": product_id,
        "creative_direction": "deterministic raw-script decomposition",
        "raw_script": script,
        "planning": {
            "mode": "automatic",
            "panel_count": total_panels,
            "panel_range": [MIN_PLANNED_PANELS, MAX_PLANNED_PANELS],
        },
        "continuity_archive": generated_archive,
        "scenes": story_scenes,
    }


def decompose_raw_script(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Public alias for callers that name the first planning stage explicitly."""

    return build_storyboard_plan(*args, **kwargs)


def plan_shots_and_panels(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Public alias for the automatic bounded shot/panel planner."""

    return build_storyboard_plan(*args, **kwargs)


def validate_panel_entity_references(story: Mapping[str, Any], *, product_id: str) -> None:
    archive = story.get("continuity_archive")
    if archive is None:
        return
    normalized = validate_continuity_archive(archive, product_id=product_id)
    known = {entity["entity_id"] for entity in normalized["entities"]}
    for scene_index, scene in enumerate(story.get("scenes", ())):
        if not isinstance(scene, Mapping):
            continue
        for beat_index, beat in enumerate(scene.get("beats", ())):
            if not isinstance(beat, Mapping):
                continue
            for shot_index, shot in enumerate(beat.get("shots", ())):
                if not isinstance(shot, Mapping):
                    continue
                for panel_index, panel in enumerate(shot.get("panels", ())):
                    if not isinstance(panel, Mapping) or "continuity_entities" not in panel:
                        continue
                    refs = panel["continuity_entities"]
                    if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes, bytearray)) or any(ref not in known for ref in refs):
                        raise StoryboardError(
                            "STORYBOARD_CONTINUITY_ENTITY_INVALID",
                            "conflict",
                            "Panel continuity_entities must reference known typed entities",
                            field_paths=(f"plan.scenes[{scene_index}].beats[{beat_index}].shots[{shot_index}].panels[{panel_index}].continuity_entities",),
                            details={"unknown": [safe_field_segment(ref) for ref in refs] if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes, bytearray)) else "invalid"},
                        )
