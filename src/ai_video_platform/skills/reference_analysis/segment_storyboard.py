"""Owner-local fine-segment observations and core storyboard derivation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .errors import ErrorCode, SkillError


OBSERVATION_FIELDS = (
    "scene",
    "shot_scale_and_camera_position",
    "camera_motion",
    "subject_motion",
    "primary_subject_action",
    "product_action_and_state",
    "package_container_prop_state",
    "subtitle_and_visible_text",
    "speech_music_sound_effect",
    "emotion_change",
    "attention_target",
    "audience_psychology",
    "narrative_function",
    "viral_mechanism",
    "conversion_function",
)


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required object is missing or invalid", field_paths=(field,))
    return {str(key): nested for key, nested in value.items()}


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required integer is invalid", field_paths=(field,))
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required text is missing or invalid", field_paths=(field,))
    return value.strip()


def build_segment_analysis(
    segments: Sequence[Mapping[str, object]],
    keyframes: Sequence[Mapping[str, object]],
    annotations: Sequence[Mapping[str, object]],
    *,
    analyzer_id: str,
) -> list[dict[str, object]]:
    """Bind offline observations to real representative frames in exact source intervals."""
    segment_intervals = {(int(item["start_ms"]), int(item["end_ms"])) for item in segments}
    normalized_annotations: dict[tuple[int, int], dict[str, object]] = {}
    for index, raw in enumerate(annotations):
        field = f"offline_analysis.segment_annotations[{index}]"
        annotation = _mapping(raw, field)
        required = {"start_ms", "end_ms", "stage_title", "observations"}
        if set(annotation) != required:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Segment annotation fields are invalid", field_paths=(field,))
        start_ms = _integer(annotation.get("start_ms"), f"{field}.start_ms")
        end_ms = _integer(annotation.get("end_ms"), f"{field}.end_ms")
        interval = (start_ms, end_ms)
        if interval not in segment_intervals or interval in normalized_annotations:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Segment annotation interval is unknown or duplicated", field_paths=(field,))
        observations = _mapping(annotation.get("observations"), f"{field}.observations")
        unexpected = sorted(set(observations) - set(OBSERVATION_FIELDS))
        if unexpected:
            raise SkillError(
                ErrorCode.VALIDATION_FAILED,
                "Segment annotation observation fields are invalid",
                field_paths=tuple(f"{field}.observations.{name}" for name in unexpected),
            )
        normalized_annotations[interval] = {
            "stage_title": _text(annotation.get("stage_title"), f"{field}.stage_title"),
            "observations": observations,
        }

    representatives = {
        str(frame["segment_id"]): str(frame["frame_id"])
        for frame in keyframes
        if frame.get("frame_role") == "representative"
    }
    analyses: list[dict[str, object]] = []
    for segment in segments:
        segment_id = str(segment["segment_id"])
        interval = (int(segment["start_ms"]), int(segment["end_ms"]))
        annotation = normalized_annotations.get(interval)
        representative = representatives.get(segment_id)
        if representative is None:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Segment representative frame is missing")
        values = annotation["observations"] if annotation is not None else {}
        observations: dict[str, dict[str, object]] = {}
        for field in OBSERVATION_FIELDS:
            raw_value = values.get(field)  # type: ignore[union-attr]
            if raw_value is None or raw_value == "UNAVAILABLE":
                observations[field] = {"value": "UNAVAILABLE", "evidence_refs": []}
            else:
                observations[field] = {
                    "value": _text(raw_value, f"segment_analysis.{segment_id}.{field}"),
                    "evidence_refs": [f"frame:{representative}"],
                }
        analyses.append({
            "segment_id": segment_id,
            "source_video_id": segment["source_video_id"],
            "start_ms": interval[0],
            "end_ms": interval[1],
            "stage_title": annotation["stage_title"] if annotation is not None else f"Segment {len(analyses) + 1}",
            "observations": observations,
            "analysis_provenance": {
                "method": "offline_local_annotation" if annotation is not None else "unavailable",
                "analyzer_id": analyzer_id,
                "representative_frame_id": representative,
            },
        })
    return analyses


__all__ = ["OBSERVATION_FIELDS", "build_segment_analysis"]
