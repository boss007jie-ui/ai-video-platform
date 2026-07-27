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
                    "evidence_refs": (
                        [f"audio:{segment_id}"]
                        if field == "speech_music_sound_effect"
                        else [f"frame:{representative}"]
                    ),
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


_MERGE_FIELDS = (
    "scene",
    "narrative_function",
    "audience_psychology",
    "viral_mechanism",
    "conversion_function",
    "subject_motion",
    "primary_subject_action",
    "product_action_and_state",
    "package_container_prop_state",
)


def _observation_value(analysis: Mapping[str, object], field: str) -> str:
    observations = analysis["observations"]
    value = observations[field]["value"]  # type: ignore[index]
    return str(value)


def _merge_signature(analysis: Mapping[str, object]) -> tuple[str, ...] | None:
    signature = tuple(_observation_value(analysis, field) for field in _MERGE_FIELDS)
    return None if any(value == "UNAVAILABLE" for value in signature) else signature


def derive_core_beats(
    segments: Sequence[Mapping[str, object]],
    analyses: Sequence[Mapping[str, object]],
    keyframes: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Merge only adjacent segments with the same available semantic purpose."""
    by_segment = {str(item["segment_id"]): item for item in analyses}
    frames_by_segment: dict[str, list[Mapping[str, object]]] = {}
    for frame in keyframes:
        frames_by_segment.setdefault(str(frame["segment_id"]), []).append(frame)

    groups: list[list[Mapping[str, object]]] = []
    prior_signature: tuple[str, ...] | None = None
    for segment in segments:
        segment_id = str(segment["segment_id"])
        analysis = by_segment.get(segment_id)
        if analysis is None:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Every fine segment requires analysis")
        signature = _merge_signature(analysis)
        if groups and signature is not None and signature == prior_signature:
            groups[-1].append(segment)
        else:
            groups.append([segment])
        prior_signature = signature

    beats: list[dict[str, object]] = []
    for index, group in enumerate(groups):
        first = group[0]
        last = group[-1]
        first_id = str(first["segment_id"])
        analysis = by_segment[first_id]
        source_segment_ids = [str(item["segment_id"]) for item in group]
        source_frames = [frame for segment_id in source_segment_ids for frame in frames_by_segment.get(segment_id, [])]
        representative = next(
            (str(frame["frame_id"]) for frame in source_frames if frame.get("frame_role") == "representative"),
            None,
        )
        if representative is None:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Core beat representative frame is missing")
        conversion = _observation_value(analysis, "conversion_function")
        beats.append({
            "beat_id": f"core-beat-{index + 1:03d}",
            "source_segment_ids": source_segment_ids,
            "source_frame_ids": [str(frame["frame_id"]) for frame in source_frames],
            "start_ms": int(first["start_ms"]),
            "end_ms": int(last["end_ms"]),
            "representative_frame_id": representative,
            "merge_reason": (
                "Adjacent segments share scene/event continuity, narrative purpose, audience psychology, mechanism, action, and product/prop state."
                if len(group) > 1
                else "Segment retains a distinct evidence-bound semantic purpose."
            ),
            "stage_title": str(analysis["stage_title"]),
            "visual_summary": _observation_value(analysis, "scene"),
            "key_action": _observation_value(analysis, "primary_subject_action"),
            "audience_psychology": _observation_value(analysis, "audience_psychology"),
            "viral_or_conversion_function": conversion,
            "function_label": conversion,
        })
    return beats


def derive_formula(beats: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Derive the video formula only from the confirmed ordered beats."""
    return {
        "value": " -> ".join(str(beat["stage_title"]) for beat in beats),
        "source_beat_ids": [str(beat["beat_id"]) for beat in beats],
        "evidence_refs": [f"frame:{beat['representative_frame_id']}" for beat in beats],
    }


__all__ = [
    "OBSERVATION_FIELDS",
    "build_segment_analysis",
    "derive_core_beats",
    "derive_formula",
]
