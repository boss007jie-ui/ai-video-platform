"""Evidence-bound storyboard analysis for an explicitly selected reference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zlib

from .errors import ErrorCode, SkillError
from .local_media import extract_local_png_frame, probe_local_audio_available
from .models import StoryboardAnalysisResult
from .replication_blueprint import ACTION_STATES, ANALYSIS_PROFILES, DEFAULT_ANALYSIS_PROFILE, NARRATIVE_ROLES
from .segment_storyboard import OBSERVATION_FIELDS as _FINE_OBSERVATION_FIELDS
from .storyboard_boards import (
    decode_png,
    render_analysis_board,
    render_motion_keyframe_atlas,
    render_replication_board,
    render_shot_evidence_board,
)


_VERSION = "1.0.0"
_OUTPUT_ROOT = "reference_analysis"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_REQUIRED = {"analysis_version", "selected_reference_video", "video_metadata", "analysis_configuration"}
_TOP_LEVEL_ALLOWED = _TOP_LEVEL_REQUIRED | {"analysis_profile", "viral_research_pack", "popular_comments"}
_CONFIG_KEYS = {"current_product", "keyframes", "timeline", "bottom_line_formula"}
_FINE_CONFIG_KEYS = {"fine_segments", "segment_analysis", "core_beats"}
_REPLICATION_CONFIG_KEYS = {
    "motion_keyframes",
    "motion_transitions",
    "narrative_event_graph",
    "scene_blocking_map",
    "replication_constraints",
    "coverage_report",
    "reference_blueprint",
}
_OBSERVATION_FIELDS = (
    "scene",
    "shot_scale",
    "camera_motion",
    "character_action",
    "product_action",
    "product_state",
    "emotion",
    "audience_psychology",
    "conversion_function",
    "viral_mechanism",
    "comment_evidence",
    "actual_reference_behavior",
    "reusable_pattern",
    "product_transfer_suggestion",
)
_TIMELINE_KEYS = {"beat_id", "start_ms", "end_ms", "stage_title", "keyframe_ids", *_OBSERVATION_FIELDS}
_FORBIDDEN_ROLE_KEYS = {
    "production_storyboard_plan",
    "production_storyboard_panel_plan",
    "production_storyboard_panel_set",
    "production_panels",
    "video_generation_storyboard_master",
    "storyboard_master",
    "provider_request",
    "provider_execution_input",
    "first_frame_mapping",
    "product_reference_image",
}
_CONTRACTS = (
    ("ReferenceStoryboardAnalysis", "avp.contract.reference-storyboard-analysis", "reference_storyboard_analysis.json"),
    ("ReferenceBeat", "avp.contract.reference-beat", "reference_storyboard_analysis.json#/reference_beats"),
    ("ReferenceShotEvidence", "avp.contract.reference-shot-evidence", "reference_storyboard_analysis.json#/shot_evidence"),
    ("ReplicationPattern", "avp.contract.replication-pattern", "reference_storyboard_analysis.json#/replication_patterns"),
    ("ReferenceAnalysisBoardManifest", "avp.contract.reference-analysis-board-manifest", "reference_storyboard_analysis.json#/board_manifest"),
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pretty(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required object is missing or invalid", field_paths=(field,))
    return {str(key): nested for key, nested in value.items()}


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required text is missing or invalid", field_paths=(field,))
    return value.strip()


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required integer is invalid", field_paths=(field,))
    return value


def _strict_keys(value: Mapping[str, object], required: set[str], allowed: set[str], field: str) -> None:
    missing = sorted(required - set(value))
    unexpected = sorted(set(value) - allowed)
    if missing or unexpected:
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "Object fields do not match the storyboard analysis schema",
            field_paths=tuple([*(f"{field}.{key}" for key in missing), *(f"{field}.{key}" for key in unexpected)]),
        )


def _forbidden_role_paths(value: object, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            path = f"{prefix}.{raw_key}" if prefix else str(raw_key)
            if key in _FORBIDDEN_ROLE_KEYS:
                findings.append(path)
            findings.extend(_forbidden_role_paths(nested, path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            findings.extend(_forbidden_role_paths(nested, f"{prefix}[{index}]"))
    return findings


def _workspace(workspace: Path) -> Path:
    supplied = Path(os.path.abspath(os.fspath(workspace)))
    if not supplied.is_dir() or supplied.is_symlink():
        raise SkillError(ErrorCode.PATH_FORBIDDEN, "Task workspace must be a real existing directory")
    return supplied.resolve()


def _source_file(workspace: Path, value: object, field: str) -> Path:
    raw = _text(value, field)
    relative = Path(raw)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise SkillError(ErrorCode.PATH_FORBIDDEN, "Input media path must be workspace-relative", field_paths=(field,))
    candidate = workspace / relative
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Input media path cannot contain links", field_paths=(field,))
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Input media is unavailable", field_paths=(field,)) from exc
    try:
        if os.path.commonpath((os.fspath(workspace), os.fspath(resolved))) != os.fspath(workspace):
            raise SkillError(ErrorCode.PATH_FORBIDDEN, "Input media escaped the workspace", field_paths=(field,))
    except ValueError as exc:
        raise SkillError(ErrorCode.PATH_FORBIDDEN, "Input media escaped the workspace", field_paths=(field,)) from exc
    if not resolved.is_file():
        raise SkillError(ErrorCode.MEDIA_INVALID, "Input media is not a file", field_paths=(field,))
    return resolved


def _validate_sha(value: object, payload: bytes, field: str) -> str:
    supplied = _text(value, field).casefold()
    if not _SHA256.fullmatch(supplied) or _digest(payload) != supplied:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Input media hash does not match", field_paths=(field,))
    return supplied


def _validate_source(request: dict[str, object], workspace: Path) -> tuple[dict[str, object], bytes]:
    source = _mapping(request.get("selected_reference_video"), "selected_reference_video")
    required = {
        "reference_id", "media_path", "sha256", "source_platform", "source_url", "source_id", "published_at",
        "collected_at", "category", "reference_brand", "reference_product", "reference_people", "provenance",
    }
    _strict_keys(source, required, required, "selected_reference_video")
    for field in required - {"reference_people", "provenance"}:
        _text(source.get(field), f"selected_reference_video.{field}")
    people = source.get("reference_people")
    if not isinstance(people, list) or any(not isinstance(person, str) or not person.strip() for person in people):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "reference_people must be an array of names", field_paths=("selected_reference_video.reference_people",))
    provenance = _mapping(source.get("provenance"), "selected_reference_video.provenance")
    if not provenance:
        raise SkillError(ErrorCode.EVIDENCE_MISSING, "Selected media provenance is required", field_paths=("selected_reference_video.provenance",))
    media_path = _source_file(workspace, source["media_path"], "selected_reference_video.media_path")
    payload = media_path.read_bytes()
    source["sha256"] = _validate_sha(source["sha256"], payload, "selected_reference_video.sha256")
    source["reference_people"] = [str(person).strip() for person in people]
    source["provenance"] = provenance
    return source, payload


def _validate_metadata(value: object) -> dict[str, object]:
    metadata = _mapping(value, "video_metadata")
    keys = {"duration_ms", "width", "height", "aspect_ratio", "media_type", "codec"}
    _strict_keys(metadata, keys, keys, "video_metadata")
    metadata["duration_ms"] = _integer(metadata.get("duration_ms"), "video_metadata.duration_ms", minimum=1)
    metadata["width"] = _integer(metadata.get("width"), "video_metadata.width", minimum=1)
    metadata["height"] = _integer(metadata.get("height"), "video_metadata.height", minimum=1)
    for field in ("aspect_ratio", "media_type", "codec"):
        metadata[field] = _text(metadata.get(field), f"video_metadata.{field}")
    return metadata


def _validate_comments(value: object) -> tuple[dict[str, object], set[str]]:
    if value is None:
        return {"status": "UNAVAILABLE", "records": []}, set()
    if not isinstance(value, list):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "popular_comments must be an array", field_paths=("popular_comments",))
    records: list[dict[str, object]] = []
    comment_ids: set[str] = set()
    for index, raw in enumerate(value):
        field = f"popular_comments[{index}]"
        comment = _mapping(raw, field)
        keys = {"comment_id", "text", "collected_at", "provenance"}
        _strict_keys(comment, keys, keys, field)
        comment_id = _text(comment.get("comment_id"), f"{field}.comment_id")
        if comment_id in comment_ids:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Comment identities must be unique", field_paths=(f"{field}.comment_id",))
        comment_ids.add(comment_id)
        comment["comment_id"] = comment_id
        comment["text"] = _text(comment.get("text"), f"{field}.text")
        comment["collected_at"] = _text(comment.get("collected_at"), f"{field}.collected_at")
        comment["provenance"] = _mapping(comment.get("provenance"), f"{field}.provenance")
        if not comment["provenance"]:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Comment provenance is required", field_paths=(f"{field}.provenance",))
        records.append(comment)
    return {"status": "AVAILABLE" if records else "UNAVAILABLE", "records": records}, comment_ids


def _validate_viral_pack(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    pack = _mapping(value, "viral_research_pack")
    keys = {"contract_identity", "contract_version", "artifact_ref", "provenance"}
    _strict_keys(pack, keys, keys, "viral_research_pack")
    if pack.get("contract_identity") != "avp.contract.viral-research-pack" or pack.get("contract_version") != _VERSION:
        raise SkillError(ErrorCode.VERSION_UNSUPPORTED, "ViralResearchPack identity or version is unsupported", field_paths=("viral_research_pack",))
    _text(pack.get("artifact_ref"), "viral_research_pack.artifact_ref")
    provenance = _mapping(pack.get("provenance"), "viral_research_pack.provenance")
    if not provenance:
        raise SkillError(ErrorCode.EVIDENCE_MISSING, "ViralResearchPack provenance is required", field_paths=("viral_research_pack.provenance",))
    pack["provenance"] = provenance
    return pack


def _validate_keyframes(
    value: object, workspace: Path, duration_ms: int,
) -> tuple[dict[str, dict[str, object]], dict[str, bytes], dict[str, tuple[int, int, bytes]]]:
    if not isinstance(value, list) or not value:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "At least one real keyframe is required", field_paths=("analysis_configuration.keyframes",))
    records: dict[str, dict[str, object]] = {}
    payloads: dict[str, bytes] = {}
    images: dict[str, tuple[int, int, bytes]] = {}
    stored_timestamps: set[tuple[str, int]] = set()
    for index, raw in enumerate(value):
        field = f"analysis_configuration.keyframes[{index}]"
        record = _mapping(raw, field)
        keys = {"keyframe_id", "timestamp_ms", "path", "sha256"}
        owner_keys = {"source_video_id", "segment_id", "frame_role"}
        semantic_keys = {"shot_id", "scene_id", "action_roles", "narrative_roles"}
        _strict_keys(record, keys, keys | owner_keys | semantic_keys, field)
        keyframe_id = _text(record.get("keyframe_id"), f"{field}.keyframe_id")
        if keyframe_id in records:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Keyframe identities must be unique", field_paths=(f"{field}.keyframe_id",))
        timestamp = _integer(record.get("timestamp_ms"), f"{field}.timestamp_ms")
        if timestamp >= duration_ms:
            raise SkillError(ErrorCode.MEDIA_INVALID, "Keyframe timestamp is outside the video", field_paths=(f"{field}.timestamp_ms",))
        path = _source_file(workspace, record.get("path"), f"{field}.path")
        payload = path.read_bytes()
        record["sha256"] = _validate_sha(record.get("sha256"), payload, f"{field}.sha256")
        try:
            images[keyframe_id] = decode_png(payload)
        except (ValueError, zlib.error) as exc:
            raise SkillError(ErrorCode.MEDIA_INVALID, "Keyframe must be a supported PNG", field_paths=(f"{field}.path",)) from exc
        record["keyframe_id"] = keyframe_id
        record["timestamp_ms"] = timestamp
        record["path"] = Path(str(record["path"])).as_posix()
        present_owner_keys = set(record) & owner_keys
        present_semantic_keys = set(record) & semantic_keys
        if present_owner_keys and present_owner_keys != owner_keys:
            raise SkillError(
                ErrorCode.VALIDATION_FAILED,
                "Fine keyframe ownership fields must be complete",
                field_paths=(field,),
            )
        if present_semantic_keys and (present_owner_keys != owner_keys or present_semantic_keys != semantic_keys):
            raise SkillError(
                ErrorCode.VALIDATION_FAILED,
                "Semantic keyframe ownership and role fields must be complete",
                field_paths=(field,),
            )
        if present_owner_keys:
            record["source_video_id"] = _text(record.get("source_video_id"), f"{field}.source_video_id")
            record["segment_id"] = _text(record.get("segment_id"), f"{field}.segment_id")
            role = _text(record.get("frame_role"), f"{field}.frame_role")
            if role not in {"start", "representative", "end", "semantic", "action_peak", "product_state_change", "subtitle_change"}:
                raise SkillError(ErrorCode.VALIDATION_FAILED, "Fine keyframe role is invalid", field_paths=(f"{field}.frame_role",))
            record["frame_role"] = role
            storage_key = (str(record["segment_id"]), timestamp)
            if storage_key in stored_timestamps:
                raise SkillError(
                    ErrorCode.VALIDATION_FAILED,
                    "A source timestamp may be stored only once per fine segment",
                    field_paths=(f"{field}.timestamp_ms",),
                )
            stored_timestamps.add(storage_key)
        if present_semantic_keys:
            record["shot_id"] = _text(record.get("shot_id"), f"{field}.shot_id")
            record["scene_id"] = _text(record.get("scene_id"), f"{field}.scene_id")
            for name, allowed in (("action_roles", ACTION_STATES), ("narrative_roles", NARRATIVE_ROLES)):
                roles = record.get(name)
                if (
                    not isinstance(roles, list)
                    or any(not isinstance(item, str) or item not in allowed for item in roles)
                    or len(roles) != len(set(roles))
                ):
                    raise SkillError(ErrorCode.VALIDATION_FAILED, "Semantic keyframe roles are invalid", field_paths=(f"{field}.{name}",))
                record[name] = list(roles)
            if record["frame_role"] == "semantic" and not (record["action_roles"] or record["narrative_roles"]):
                raise SkillError(
                    ErrorCode.EVIDENCE_MISSING,
                    "A semantic keyframe requires an action or narrative role",
                    field_paths=(field,),
                )
        records[keyframe_id] = record
        payloads[keyframe_id] = payload
    return records, payloads, images
def _is_unavailable_observation(value: str) -> bool:
    return value == "UNAVAILABLE" or value.startswith("DRAFT: UNAVAILABLE")




def _observation(value: object, field: str, allowed_refs: set[str]) -> dict[str, object]:
    observation = _mapping(value, field)
    _strict_keys(observation, {"value", "evidence_refs"}, {"value", "evidence_refs"}, field)
    observed = _text(observation.get("value"), f"{field}.value")
    refs = observation.get("evidence_refs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "evidence_refs must be an array", field_paths=(f"{field}.evidence_refs",))
    unknown = [ref for ref in refs if ref not in allowed_refs]
    unavailable = _is_unavailable_observation(observed)
    if unknown or (not unavailable and not refs) or (unavailable and refs):
        raise SkillError(ErrorCode.EVIDENCE_MISSING, "Observation is not traceable to available evidence", field_paths=(f"{field}.evidence_refs",))
    return {"value": observed, "evidence_refs": list(refs)}


def _validate_timeline(
    value: object,
    *,
    duration_ms: int,
    keyframes: dict[str, dict[str, object]],
    allowed_refs: set[str],
    reference_identities: tuple[str, ...],
) -> tuple[list[dict[str, object]], set[str]]:
    if not isinstance(value, list) or not value:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "timeline must be a non-empty array", field_paths=("analysis_configuration.timeline",))
    beats: list[dict[str, object]] = []
    used_keyframes: set[str] = set()
    prior_end = 0
    beat_ids: set[str] = set()
    for index, raw in enumerate(value):
        field = f"analysis_configuration.timeline[{index}]"
        beat = _mapping(raw, field)
        _strict_keys(beat, _TIMELINE_KEYS, _TIMELINE_KEYS, field)
        beat_id = _text(beat.get("beat_id"), f"{field}.beat_id")
        if beat_id in beat_ids:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Beat identities must be unique", field_paths=(f"{field}.beat_id",))
        beat_ids.add(beat_id)
        start = _integer(beat.get("start_ms"), f"{field}.start_ms")
        end = _integer(beat.get("end_ms"), f"{field}.end_ms", minimum=1)
        if start != prior_end or end <= start or end > duration_ms:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Timeline must be contiguous, ordered, and inside the video duration", field_paths=(field,))
        ids = beat.get("keyframe_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(item, str) for item in ids):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Every beat requires real keyframe evidence", field_paths=(f"{field}.keyframe_ids",))
        for keyframe_id in ids:
            if keyframe_id not in keyframes:
                raise SkillError(ErrorCode.EVIDENCE_MISSING, "Beat references an unknown keyframe", field_paths=(f"{field}.keyframe_ids",))
            timestamp = int(keyframes[keyframe_id]["timestamp_ms"])
            if not start <= timestamp < end:
                raise SkillError(ErrorCode.MEDIA_INVALID, "Keyframe timestamp is outside its exact beat interval", field_paths=(f"{field}.keyframe_ids",))
            if keyframe_id in used_keyframes:
                raise SkillError(ErrorCode.EVIDENCE_MISSING, "A keyframe may bind to only one exact beat interval", field_paths=(f"{field}.keyframe_ids",))
            used_keyframes.add(keyframe_id)
        normalized: dict[str, object] = {
            "beat_id": beat_id,
            "interval": {"start_ms": start, "end_ms": end},
            "stage_title": _text(beat.get("stage_title"), f"{field}.stage_title"),
            "keyframe_ids": list(ids),
        }
        for name in _OBSERVATION_FIELDS:
            normalized[name] = _observation(beat.get(name), f"{field}.{name}", allowed_refs)
        comment_evidence = normalized["comment_evidence"]
        if (
            not _is_unavailable_observation(str(comment_evidence["value"]))  # type: ignore[index]
            and not any(str(ref).startswith("comment:") for ref in comment_evidence["evidence_refs"])  # type: ignore[index]
        ):
            raise SkillError(
                ErrorCode.EVIDENCE_MISSING,
                "Comment evidence must cite an available comment record",
                field_paths=(f"{field}.comment_evidence.evidence_refs",),
            )
        transfer = str(normalized["product_transfer_suggestion"]["value"]).casefold()  # type: ignore[index]
        if transfer != "unavailable" and any(identity.casefold() in transfer for identity in reference_identities if len(identity.strip()) >= 4):
            raise SkillError(
                ErrorCode.ARTIFACT_ROLE_FORBIDDEN,
                "Product adaptation cannot copy reference brand, product, or person identity",
                field_paths=(f"{field}.product_transfer_suggestion.value",),
            )
        beats.append(normalized)
        prior_end = end
    if prior_end != duration_ms:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Timeline must cover the selected video duration", field_paths=("analysis_configuration.timeline",))
    if used_keyframes != set(keyframes):
        raise SkillError(ErrorCode.EVIDENCE_MISSING, "Every declared keyframe must bind to one beat", field_paths=("analysis_configuration.keyframes",))
    return beats, used_keyframes


def _validate_fine_package(
    config: Mapping[str, object],
    *,
    duration_ms: int,
    source_video_id: str,
    keyframes: Mapping[str, Mapping[str, object]],
    timeline: list[dict[str, object]],
    formula: Mapping[str, object],
    audio_available: bool,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    raw_segments = config.get("fine_segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "fine_segments must be a non-empty array", field_paths=("analysis_configuration.fine_segments",))
    segments: list[dict[str, object]] = []
    prior_end = 0
    segment_ids: set[str] = set()
    segment_keys = {
        "segment_id", "source_video_id", "start_ms", "end_ms", "duration_ms",
        "segmentation_reasons", "shot_id", "scene_id", "previous_segment_id", "next_segment_id",
    }
    for index, raw in enumerate(raw_segments):
        field = f"analysis_configuration.fine_segments[{index}]"
        segment = _mapping(raw, field)
        _strict_keys(segment, segment_keys, segment_keys, field)
        segment_id = _text(segment.get("segment_id"), f"{field}.segment_id")
        if segment_id in segment_ids:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Fine segment identities must be unique", field_paths=(f"{field}.segment_id",))
        segment_ids.add(segment_id)
        if _text(segment.get("source_video_id"), f"{field}.source_video_id") != source_video_id:
            raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Fine segment source video does not match the selected reference", field_paths=(f"{field}.source_video_id",))
        segment["shot_id"] = _text(segment.get("shot_id"), f"{field}.shot_id")
        segment["scene_id"] = _text(segment.get("scene_id"), f"{field}.scene_id")
        start_ms = _integer(segment.get("start_ms"), f"{field}.start_ms")
        end_ms = _integer(segment.get("end_ms"), f"{field}.end_ms", minimum=1)
        declared_duration = _integer(segment.get("duration_ms"), f"{field}.duration_ms", minimum=1)
        if start_ms != prior_end or end_ms <= start_ms or end_ms > duration_ms or declared_duration != end_ms - start_ms:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Fine segments must be contiguous, ordered, and duration exact", field_paths=(field,))
        expected_previous = None if index == 0 else str(raw_segments[index - 1]["segment_id"])
        expected_next = None if index + 1 == len(raw_segments) else str(raw_segments[index + 1]["segment_id"])
        if segment.get("previous_segment_id") != expected_previous or segment.get("next_segment_id") != expected_next:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Fine segment adjacency links are invalid", field_paths=(field,))
        reasons = segment.get("segmentation_reasons")
        if not isinstance(reasons, list) or not reasons:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Fine segment boundary reasons are required", field_paths=(f"{field}.segmentation_reasons",))
        segment.update({"segment_id": segment_id, "start_ms": start_ms, "end_ms": end_ms, "duration_ms": declared_duration})
        segments.append(segment)
        prior_end = end_ms
    if prior_end != duration_ms:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Fine segments must cover the selected video duration", field_paths=("analysis_configuration.fine_segments",))

    frame_ids_by_segment: dict[str, list[str]] = {segment_id: [] for segment_id in segment_ids}
    roles_by_segment: dict[str, set[str]] = {segment_id: set() for segment_id in segment_ids}
    for frame_id, frame in keyframes.items():
        segment_id = str(frame.get("segment_id", ""))
        if segment_id not in segment_ids or frame.get("source_video_id") != source_video_id:
            raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Fine keyframe ownership does not match a source segment", field_paths=("analysis_configuration.keyframes",))
        segment = next(item for item in segments if item["segment_id"] == segment_id)
        timestamp_ms = int(frame["timestamp_ms"])
        if not int(segment["start_ms"]) <= timestamp_ms < int(segment["end_ms"]):
            raise SkillError(ErrorCode.MEDIA_INVALID, "Fine keyframe timestamp is outside its source segment", field_paths=("analysis_configuration.keyframes",))
        if "shot_id" in frame and (
            frame.get("shot_id") != segment["shot_id"] or frame.get("scene_id") != segment["scene_id"]
        ):
            raise SkillError(
                ErrorCode.REFERENCE_MISMATCH,
                "Fine keyframe shot or scene ownership does not match its segment",
                field_paths=("analysis_configuration.keyframes",),
            )
        frame_ids_by_segment[segment_id].append(frame_id)
        roles_by_segment[segment_id].add(str(frame.get("frame_role")))
    for segment_id, roles in roles_by_segment.items():
        if not {"start", "representative", "end"}.issubset(roles):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Every fine segment requires start, representative, and end frames", field_paths=(f"segment:{segment_id}",))

    raw_analyses = config.get("segment_analysis")
    if not isinstance(raw_analyses, list) or len(raw_analyses) != len(segments):
        raise SkillError(ErrorCode.EVIDENCE_MISSING, "Every fine segment requires one analysis", field_paths=("analysis_configuration.segment_analysis",))
    analyses: list[dict[str, object]] = []
    analysis_by_id: dict[str, dict[str, object]] = {}
    analysis_keys = {
        "segment_id", "source_video_id", "start_ms", "end_ms", "stage_title", "observations",
        "facts", "motion_evidence", "audio_evidence", "subtitle_evidence", "analysis_provenance",
    }
    segment_by_id = {str(item["segment_id"]): item for item in segments}
    for index, raw in enumerate(raw_analyses):
        field = f"analysis_configuration.segment_analysis[{index}]"
        analysis = _mapping(raw, field)
        _strict_keys(analysis, analysis_keys, analysis_keys, field)
        segment_id = _text(analysis.get("segment_id"), f"{field}.segment_id")
        segment = segment_by_id.get(segment_id)
        if segment is None or segment_id in analysis_by_id:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Segment analysis identity is unknown or duplicated", field_paths=(f"{field}.segment_id",))
        if (
            analysis.get("source_video_id") != source_video_id
            or analysis.get("start_ms") != segment["start_ms"]
            or analysis.get("end_ms") != segment["end_ms"]
        ):
            raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Segment analysis source interval does not match", field_paths=(field,))
        _text(analysis.get("stage_title"), f"{field}.stage_title")
        observations = _mapping(analysis.get("observations"), f"{field}.observations")
        if set(observations) != set(_FINE_OBSERVATION_FIELDS):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Segment analysis observation set is incomplete", field_paths=(f"{field}.observations",))
        for name in _FINE_OBSERVATION_FIELDS:
            observation = _mapping(observations[name], f"{field}.observations.{name}")
            _strict_keys(observation, {"value", "evidence_refs"}, {"value", "evidence_refs"}, f"{field}.observations.{name}")
            value = _text(observation.get("value"), f"{field}.observations.{name}.value")
            refs = observation.get("evidence_refs")
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise SkillError(ErrorCode.VALIDATION_FAILED, "Fine observation evidence_refs must be an array", field_paths=(f"{field}.observations.{name}.evidence_refs",))
            expected_frame_ids = set(frame_ids_by_segment[segment_id])
            allowed_segment_refs = {
                *(f"frame:{frame_id}" for frame_id in expected_frame_ids),
            }
            if audio_available:
                allowed_segment_refs.add(f"audio:{segment_id}")
            if value == "UNAVAILABLE":
                if refs:
                    raise SkillError(ErrorCode.EVIDENCE_MISSING, "Unavailable fine observation cannot cite evidence", field_paths=(f"{field}.observations.{name}.evidence_refs",))
            elif not refs or not set(refs).issubset(allowed_segment_refs):
                raise SkillError(ErrorCode.EVIDENCE_MISSING, "Fine observation must cite in-segment frame or audio evidence", field_paths=(f"{field}.observations.{name}.evidence_refs",))
        _mapping(analysis.get("analysis_provenance"), f"{field}.analysis_provenance")
        for name in ("facts", "motion_evidence", "audio_evidence", "subtitle_evidence"):
            if not isinstance(analysis.get(name), list):
                raise SkillError(
                    ErrorCode.VALIDATION_FAILED,
                    "Fine segment replication evidence must be an array",
                    field_paths=(f"{field}.{name}",),
                )
        if any(
            not isinstance(ref, str) or ref != f"audio:{segment_id}"
            for ref in analysis["audio_evidence"]
        ):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Audio evidence crossed its source segment", field_paths=(f"{field}.audio_evidence",))
        expected_frame_refs = {f"frame:{frame_id}" for frame_id in frame_ids_by_segment[segment_id]}
        if any(
            not isinstance(ref, str) or ref not in expected_frame_refs
            for ref in analysis["subtitle_evidence"]
        ):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Subtitle evidence crossed its source segment", field_paths=(f"{field}.subtitle_evidence",))
        analyses.append(analysis)
        analysis_by_id[segment_id] = analysis
    if set(analysis_by_id) != segment_ids:
        raise SkillError(ErrorCode.EVIDENCE_MISSING, "Segment analysis coverage is incomplete", field_paths=("analysis_configuration.segment_analysis",))

    raw_beats = config.get("core_beats")
    if not isinstance(raw_beats, list) or not raw_beats:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "core_beats must be a non-empty array", field_paths=("analysis_configuration.core_beats",))
    beat_keys = {
        "beat_id", "source_segment_ids", "source_frame_ids", "start_ms", "end_ms",
        "representative_frame_id", "merge_reason", "stage_title", "visual_summary", "key_action",
        "audience_psychology", "viral_or_conversion_function", "function_label",
    }
    beats: list[dict[str, object]] = []
    segment_cursor = 0
    beat_ids: set[str] = set()
    for index, raw in enumerate(raw_beats):
        field = f"analysis_configuration.core_beats[{index}]"
        beat = _mapping(raw, field)
        _strict_keys(beat, beat_keys, beat_keys, field)
        beat_id = _text(beat.get("beat_id"), f"{field}.beat_id")
        if beat_id in beat_ids:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Core beat identities must be unique", field_paths=(f"{field}.beat_id",))
        beat_ids.add(beat_id)
        source_segment_ids = beat.get("source_segment_ids")
        if not isinstance(source_segment_ids, list) or not source_segment_ids or any(not isinstance(item, str) for item in source_segment_ids):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Core beat source_segment_ids are invalid", field_paths=(f"{field}.source_segment_ids",))
        expected_ids = [str(item["segment_id"]) for item in segments[segment_cursor : segment_cursor + len(source_segment_ids)]]
        if source_segment_ids != expected_ids:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Core beats must partition adjacent fine segments in order", field_paths=(f"{field}.source_segment_ids",))
        segment_cursor += len(source_segment_ids)
        source_frames = beat.get("source_frame_ids")
        expected_frames = [frame_id for segment_id in source_segment_ids for frame_id in frame_ids_by_segment[segment_id]]
        if not isinstance(source_frames, list) or source_frames != expected_frames:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Core beat source_frame_ids must cover its source segments", field_paths=(f"{field}.source_frame_ids",))
        first_segment = segment_by_id[source_segment_ids[0]]
        last_segment = segment_by_id[source_segment_ids[-1]]
        if beat.get("start_ms") != first_segment["start_ms"] or beat.get("end_ms") != last_segment["end_ms"]:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Core beat interval must equal its source segment range", field_paths=(field,))
        representative = _text(beat.get("representative_frame_id"), f"{field}.representative_frame_id")
        representative_record = keyframes.get(representative)
        if representative not in source_frames or representative_record is None or representative_record.get("frame_role") != "representative":
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Core beat representative must be an owned representative frame", field_paths=(f"{field}.representative_frame_id",))
        for name in beat_keys - {"source_segment_ids", "source_frame_ids", "start_ms", "end_ms"}:
            if name not in {"beat_id", "representative_frame_id"}:
                _text(beat.get(name), f"{field}.{name}")
        if index >= len(timeline):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Core beat timeline mapping is incomplete", field_paths=(field,))
        mapped = timeline[index]
        if mapped["beat_id"] != beat_id or mapped["interval"] != {"start_ms": beat["start_ms"], "end_ms": beat["end_ms"]} or mapped["keyframe_ids"] != source_frames:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Core beat does not match the canonical timeline", field_paths=(field,))
        beats.append(beat)
    if segment_cursor != len(segments) or len(timeline) != len(beats):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Core beats must cover every fine segment exactly once", field_paths=("analysis_configuration.core_beats",))
    expected_formula = " -> ".join(str(beat["stage_title"]) for beat in beats)
    if formula.get("value") != expected_formula:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Bottom-line formula must derive from ordered core beats", field_paths=("analysis_configuration.bottom_line_formula.value",))
    expected_formula_refs = [f"keyframe:{beat['representative_frame_id']}" for beat in beats]
    if formula.get("evidence_refs") != expected_formula_refs:
        raise SkillError(ErrorCode.EVIDENCE_MISSING, "Bottom-line formula evidence must cite ordered beat representatives", field_paths=("analysis_configuration.bottom_line_formula.evidence_refs",))
    return segments, analyses, beats


def _string_list(value: object, field: str, *, allow_empty: bool = True) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Expected an ordered list of unique identifiers", field_paths=(field,))
    return list(value)


def _object_list(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Expected an array of objects", field_paths=(field,))
    return [_mapping(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _validate_replication_package(
    config: Mapping[str, object],
    *,
    profile: str,
    source_video_id: str,
    keyframes: Mapping[str, Mapping[str, object]],
    fine_segments: Sequence[Mapping[str, object]],
    segment_analysis: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    field_root = "analysis_configuration"
    frame_ids = set(keyframes)
    segment_by_id = {str(item["segment_id"]): item for item in fine_segments}
    segment_ids = set(segment_by_id)
    if not segment_ids:
        raise SkillError(ErrorCode.EVIDENCE_MISSING, "Replication artifacts require fine segment evidence", field_paths=(f"{field_root}.fine_segments",))
    for frame_id, frame in keyframes.items():
        if not {"shot_id", "scene_id", "action_roles", "narrative_roles"}.issubset(frame):
            raise SkillError(
                ErrorCode.EVIDENCE_MISSING,
                "Replication keyframes require complete semantic ownership",
                field_paths=(f"{field_root}.keyframes.{frame_id}",),
            )

    package = {name: _mapping(config.get(name), f"{field_root}.{name}") for name in _REPLICATION_CONFIG_KEYS}

    def require_profile(value: Mapping[str, object], field: str) -> None:
        if value.get("analysis_profile") != profile:
            raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Replication artifact profile does not match the request", field_paths=(f"{field}.analysis_profile",))

    motion = package["motion_keyframes"]
    motion_field = f"{field_root}.motion_keyframes"
    _strict_keys(motion, {"analysis_profile", "status", "action_chains", "transitions"}, {"analysis_profile", "status", "action_chains", "transitions"}, motion_field)
    require_profile(motion, motion_field)
    _text(motion.get("status"), f"{motion_field}.status")
    action_chains = _object_list(motion.get("action_chains"), f"{motion_field}.action_chains")
    action_ids: set[str] = set()
    action_state_pairs: set[tuple[str, str]] = set()
    for index, chain in enumerate(action_chains):
        field = f"{motion_field}.action_chains[{index}]"
        chain_keys = {
            "action_id", "actor", "body_part", "start_pose", "end_pose", "motion_direction", "motion_path",
            "motion_speed", "action_duration_ms", "joint_or_limb_change", "hand_state", "object_state_before",
            "object_state_after", "camera_motion", "source_segments", "source_frames", "states",
        }
        _strict_keys(chain, chain_keys, chain_keys, field)
        action_id = _text(chain.get("action_id"), f"{field}.action_id")
        if action_id in action_ids:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Motion action identities must be unique", field_paths=(f"{field}.action_id",))
        action_ids.add(action_id)
        for name in chain_keys - {"action_id", "action_duration_ms", "source_segments", "source_frames", "states"}:
            _text(chain.get(name), f"{field}.{name}")
        states = _object_list(chain.get("states"), f"{field}.states")
        if len(states) < 2:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Motion action requires at least two source states", field_paths=(f"{field}.states",))
        normalized_frame_ids: list[str] = []
        normalized_segment_ids: list[str] = []
        prior_timestamp = -1
        for state_index, state in enumerate(states):
            state_field = f"{field}.states[{state_index}]"
            state_keys = {"action_state", "timestamp_ms", "frame_id", "contact_state", "source_segment_id", "source_frame_id"}
            source_scan_keys = {"evidence_origin", "source_evidence"}
            _strict_keys(state, state_keys, state_keys | source_scan_keys, state_field)
            present_source_scan_keys = source_scan_keys.intersection(state)
            if present_source_scan_keys and present_source_scan_keys != source_scan_keys:
                raise SkillError(
                    ErrorCode.VALIDATION_FAILED,
                    "Motion source-scan evidence is incomplete",
                    field_paths=(state_field,),
                )
            role = _text(state.get("action_state"), f"{state_field}.action_state")
            frame_id = _text(state.get("frame_id"), f"{state_field}.frame_id")
            source_frame_id = _text(state.get("source_frame_id"), f"{state_field}.source_frame_id")
            segment_id = _text(state.get("source_segment_id"), f"{state_field}.source_segment_id")
            timestamp_ms = _integer(state.get("timestamp_ms"), f"{state_field}.timestamp_ms")
            if present_source_scan_keys:
                if _text(state.get("evidence_origin"), f"{state_field}.evidence_origin") != "local_source_scan":
                    raise SkillError(ErrorCode.VALIDATION_FAILED, "Motion evidence origin is invalid", field_paths=(state_field,))
                source_evidence = _mapping(state.get("source_evidence"), f"{state_field}.source_evidence")
                source_evidence_keys = {"timestamp_ms", "method", "score"}
                _strict_keys(source_evidence, source_evidence_keys, source_evidence_keys, f"{state_field}.source_evidence")
                score = source_evidence.get("score")
                if (
                    _integer(source_evidence.get("timestamp_ms"), f"{state_field}.source_evidence.timestamp_ms") != timestamp_ms
                    or _text(source_evidence.get("method"), f"{state_field}.source_evidence.method") != "local_rgb_frame_difference"
                    or isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not 0 < float(score) <= 1
                ):
                    raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Motion source-scan evidence is invalid", field_paths=(state_field,))
            if role not in ACTION_STATES or frame_id != source_frame_id or frame_id not in keyframes:
                raise SkillError(ErrorCode.EVIDENCE_MISSING, "Motion state references invalid source-frame evidence", field_paths=(state_field,))
            frame = keyframes[frame_id]
            if (
                segment_id not in segment_ids
                or frame.get("segment_id") != segment_id
                or frame.get("source_video_id") != source_video_id
                or frame.get("timestamp_ms") != timestamp_ms
                or role not in frame.get("action_roles", [])
                or timestamp_ms <= prior_timestamp
            ):
                raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Motion state does not match its source frame", field_paths=(state_field,))
            _text(state.get("contact_state"), f"{state_field}.contact_state")
            prior_timestamp = timestamp_ms
            normalized_frame_ids.append(frame_id)
            normalized_segment_ids.append(segment_id)
        expected_frames = list(dict.fromkeys(normalized_frame_ids))
        expected_segments = list(dict.fromkeys(normalized_segment_ids))
        if _string_list(chain.get("source_frames"), f"{field}.source_frames", allow_empty=False) != expected_frames:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Motion chain source frames are inconsistent", field_paths=(f"{field}.source_frames",))
        if _string_list(chain.get("source_segments"), f"{field}.source_segments", allow_empty=False) != expected_segments:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Motion chain source segments are inconsistent", field_paths=(f"{field}.source_segments",))
        if chain.get("action_duration_ms") != int(states[-1]["timestamp_ms"]) - int(states[0]["timestamp_ms"]):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Motion chain duration is inconsistent", field_paths=(f"{field}.action_duration_ms",))
        action_state_pairs.update(zip(normalized_frame_ids, normalized_frame_ids[1:]))

    transitions_wrapper = package["motion_transitions"]
    transitions_field = f"{field_root}.motion_transitions"
    _strict_keys(transitions_wrapper, {"analysis_profile", "transitions"}, {"analysis_profile", "transitions"}, transitions_field)
    require_profile(transitions_wrapper, transitions_field)
    transitions = _object_list(transitions_wrapper.get("transitions"), f"{transitions_field}.transitions")
    if motion.get("transitions") != transitions_wrapper.get("transitions"):
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Motion transition publications disagree", field_paths=(transitions_field,))
    transition_keys = {
        "from_frame_id", "to_frame_id", "start_ms", "end_ms", "duration_ms", "actor", "body_part",
        "motion_path", "direction", "speed_profile", "contact_state_before", "contact_state_during",
        "contact_state_after", "product_motion", "camera_motion", "continuity_notes",
    }
    for index, transition in enumerate(transitions):
        field = f"{transitions_field}.transitions[{index}]"
        _strict_keys(transition, transition_keys, transition_keys, field)
        before = _text(transition.get("from_frame_id"), f"{field}.from_frame_id")
        after = _text(transition.get("to_frame_id"), f"{field}.to_frame_id")
        if before not in frame_ids or after not in frame_ids or (before, after) not in action_state_pairs:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Motion transition must connect adjacent evidenced action frames", field_paths=(field,))
        start_ms = _integer(transition.get("start_ms"), f"{field}.start_ms")
        end_ms = _integer(transition.get("end_ms"), f"{field}.end_ms", minimum=1)
        if (
            keyframes[before]["timestamp_ms"] != start_ms
            or keyframes[after]["timestamp_ms"] != end_ms
            or transition.get("duration_ms") != end_ms - start_ms
        ):
            raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Motion transition timing does not match source frames", field_paths=(field,))

    narrative = package["narrative_event_graph"]
    narrative_field = f"{field_root}.narrative_event_graph"
    narrative_keys = {"analysis_profile", "status", "method", "facts", "events", "causal_edges", "global_story", "repeated_product_proof_loops"}
    _strict_keys(narrative, narrative_keys, narrative_keys, narrative_field)
    require_profile(narrative, narrative_field)
    _text(narrative.get("status"), f"{narrative_field}.status")
    _text(narrative.get("method"), f"{narrative_field}.method")
    facts = _object_list(narrative.get("facts"), f"{narrative_field}.facts")
    fact_ids: set[str] = set()
    fact_frame_ids: set[str] = set()
    for index, fact in enumerate(facts):
        field = f"{narrative_field}.facts[{index}]"
        fact_id = _text(fact.get("fact_id"), f"{field}.fact_id")
        if fact_id in fact_ids or any(name in fact for name in ("narrative_role", "proof_loop_id", "repeated_structure_id")):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Narrative fact must contain observations rather than derived story labels", field_paths=(field,))
        fact_ids.add(fact_id)
        source_frames = _string_list(fact.get("source_frames"), f"{field}.source_frames", allow_empty=False)
        fact_frame_ids.update(source_frames)
        source_segments = _string_list(fact.get("source_segments"), f"{field}.source_segments", allow_empty=False)
        if any(frame_id not in keyframes for frame_id in source_frames):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Narrative fact references an unknown source frame", field_paths=(f"{field}.source_frames",))
        derived_segments = list(dict.fromkeys(str(keyframes[frame_id]["segment_id"]) for frame_id in source_frames))
        if source_segments != derived_segments or any(
            keyframes[frame_id].get("source_video_id") != source_video_id
            for frame_id in source_frames
        ):
            raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Narrative fact evidence crossed its source ownership", field_paths=(field,))
        audio_refs = _string_list(fact.get("audio_evidence"), f"{field}.audio_evidence")
        subtitle_refs = _string_list(fact.get("subtitle_evidence"), f"{field}.subtitle_evidence")
        if any(ref not in {f"audio:{segment_id}" for segment_id in source_segments} for ref in audio_refs) or any(
            ref not in {f"frame:{frame_id}" for frame_id in source_frames} for ref in subtitle_refs
        ):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Narrative fact audiovisual evidence crossed its source", field_paths=(field,))

    events = _object_list(narrative.get("events"), f"{narrative_field}.events")
    event_ids: set[str] = set()
    event_frame_ids: set[str] = set()
    for index, event in enumerate(events):
        field = f"{narrative_field}.events[{index}]"
        event_id = _text(event.get("event_id"), f"{field}.event_id")
        if event_id in event_ids:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Narrative event identity is invalid", field_paths=(f"{field}.event_id",))
        event_ids.add(event_id)
        source_frames = _string_list(event.get("source_frames"), f"{field}.source_frames", allow_empty=False)
        event_frame_ids.update(source_frames)
        source_segments = _string_list(event.get("source_segments"), f"{field}.source_segments", allow_empty=False)
        roles = _string_list(event.get("narrative_roles"), f"{field}.narrative_roles")
        if any(role not in NARRATIVE_ROLES for role in roles):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Narrative event role is invalid", field_paths=(f"{field}.narrative_roles",))
        if any(frame_id not in keyframes for frame_id in source_frames):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Narrative event references an unknown source frame", field_paths=(f"{field}.source_frames",))
        derived_segments = list(dict.fromkeys(str(keyframes[frame_id]["segment_id"]) for frame_id in source_frames))
        source_ownership_crossed = any(
            keyframes[frame_id].get("source_video_id") != source_video_id
            for frame_id in source_frames
        )
        role_evidence_missing = bool(roles) and not any(
            set(roles).intersection(keyframes[frame_id].get("narrative_roles", []))
            for frame_id in source_frames
        )
        if source_segments != derived_segments or source_ownership_crossed or role_evidence_missing:
            raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Narrative event evidence crossed its source ownership", field_paths=(field,))
        audio_refs = _string_list(event.get("audio_evidence"), f"{field}.audio_evidence")
        subtitle_refs = _string_list(event.get("subtitle_evidence"), f"{field}.subtitle_evidence")
        if any(ref not in {f"audio:{segment_id}" for segment_id in source_segments} for ref in audio_refs) or any(
            ref not in {f"frame:{frame_id}" for frame_id in source_frames} for ref in subtitle_refs
        ):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Narrative event audiovisual evidence crossed its source", field_paths=(field,))
    if event_frame_ids != fact_frame_ids:
        raise SkillError(ErrorCode.EVIDENCE_MISSING, "Narrative events do not cover all facts", field_paths=(f"{narrative_field}.events",))
    for index, edge in enumerate(_object_list(narrative.get("causal_edges"), f"{narrative_field}.causal_edges")):
        field = f"{narrative_field}.causal_edges[{index}]"
        if edge.get("from_event_id") not in event_ids or edge.get("to_event_id") not in event_ids:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Causal edge references an unknown event", field_paths=(field,))
        evidence_frames = _string_list(edge.get("evidence_frames"), f"{field}.evidence_frames", allow_empty=False)
        if any(frame_id not in frame_ids for frame_id in evidence_frames):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Causal edge references an unknown frame", field_paths=(field,))
    for index, node in enumerate(_object_list(narrative.get("global_story"), f"{narrative_field}.global_story")):
        field = f"{narrative_field}.global_story[{index}]"
        if node.get("event_id") not in event_ids or node.get("role") not in NARRATIVE_ROLES:
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Global story node is not traceable to an event", field_paths=(field,))
        if any(frame_id not in frame_ids for frame_id in _string_list(node.get("source_frames"), f"{field}.source_frames", allow_empty=False)):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Global story node references an unknown frame", field_paths=(field,))
    for index, loop in enumerate(_object_list(narrative.get("repeated_product_proof_loops"), f"{narrative_field}.repeated_product_proof_loops")):
        field = f"{narrative_field}.repeated_product_proof_loops[{index}]"
        source_frames = _string_list(loop.get("source_frames"), f"{field}.source_frames", allow_empty=False)
        source_segments = _string_list(loop.get("source_segments"), f"{field}.source_segments", allow_empty=False)
        if any(frame_id not in frame_ids for frame_id in source_frames) or source_segments != list(
            dict.fromkeys(str(keyframes[frame_id]["segment_id"]) for frame_id in source_frames)
        ):
            raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Repeated proof loop evidence crossed its source", field_paths=(field,))

    flattened_analysis_facts = [fact for analysis in segment_analysis for fact in analysis["facts"]]  # type: ignore[union-attr]
    if {_canonical(fact) for fact in flattened_analysis_facts} != {_canonical(fact) for fact in facts}:
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Segment facts disagree with the narrative graph", field_paths=(f"{field_root}.segment_analysis",))
    for index, analysis in enumerate(segment_analysis):
        segment_id = str(analysis["segment_id"])
        for evidence in analysis["motion_evidence"]:  # type: ignore[union-attr]
            evidence_field = f"{field_root}.segment_analysis[{index}].motion_evidence"
            if evidence.get("action_id") not in action_ids or any(
                frame_id not in keyframes or keyframes[frame_id].get("segment_id") != segment_id
                for frame_id in _string_list(evidence.get("source_frames"), f"{evidence_field}.source_frames", allow_empty=False)
            ):
                raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Segment motion evidence crossed its source", field_paths=(evidence_field,))

    scene_map = package["scene_blocking_map"]
    scene_field = f"{field_root}.scene_blocking_map"
    _strict_keys(scene_map, {"analysis_profile", "status", "scenes"}, {"analysis_profile", "status", "scenes"}, scene_field)
    require_profile(scene_map, scene_field)
    scene_ids: set[str] = set()
    for index, scene in enumerate(_object_list(scene_map.get("scenes"), f"{scene_field}.scenes")):
        field = f"{scene_field}.scenes[{index}]"
        scene_id = _text(scene.get("scene_id"), f"{field}.scene_id")
        if scene_id in scene_ids:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Scene identities must be unique", field_paths=(f"{field}.scene_id",))
        scene_ids.add(scene_id)
        source_segments = _string_list(scene.get("source_segments"), f"{field}.source_segments", allow_empty=False)
        source_frames = _string_list(scene.get("source_frames"), f"{field}.source_frames")
        if any(segment_id not in segment_by_id or segment_by_id[segment_id]["scene_id"] != scene_id for segment_id in source_segments) or any(
            frame_id not in keyframes or keyframes[frame_id].get("scene_id") != scene_id for frame_id in source_frames
        ):
            raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Scene blocking evidence crossed its scene", field_paths=(field,))

    constraints = package["replication_constraints"]
    constraints_field = f"{field_root}.replication_constraints"
    require_profile(constraints, constraints_field)
    if set(_string_list(constraints.get("source_scene_ids"), f"{constraints_field}.source_scene_ids")) != scene_ids:
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Replication constraints reference unknown scenes", field_paths=(f"{constraints_field}.source_scene_ids",))

    coverage = package["coverage_report"]
    coverage_field = f"{field_root}.coverage_report"
    require_profile(coverage, coverage_field)
    for coverage_name, role_name in (("motion_coverage", "action_roles"), ("narrative_coverage", "narrative_roles")):
        coverage_item = _mapping(coverage.get(coverage_name), f"{coverage_field}.{coverage_name}")
        if _integer(coverage_item.get("iterations"), f"{coverage_field}.{coverage_name}.iterations") > 1:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Coverage supplementation must be bounded to one pass", field_paths=(f"{coverage_field}.{coverage_name}.iterations",))
        added_ids = _string_list(coverage_item.get("added_frame_ids"), f"{coverage_field}.{coverage_name}.added_frame_ids")
        if coverage_item.get("added_frame_count") != len(added_ids) or any(
            frame_id not in keyframes or not keyframes[frame_id].get(role_name) for frame_id in added_ids
        ):
            raise SkillError(ErrorCode.EVIDENCE_MISSING, "Coverage-added frames are not valid semantic evidence", field_paths=(f"{coverage_field}.{coverage_name}.added_frame_ids",))
        if not isinstance(coverage_item.get("unresolved_gaps"), list):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Coverage unresolved_gaps must be an array", field_paths=(f"{coverage_field}.{coverage_name}.unresolved_gaps",))
        if not isinstance(coverage_item.get("checks"), list) or any(
            not isinstance(check, Mapping) for check in coverage_item["checks"]
        ):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Coverage checks must be structured records", field_paths=(f"{coverage_field}.{coverage_name}.checks",))
    transition_summary = _mapping(coverage.get("motion_transitions"), f"{coverage_field}.motion_transitions")
    if transition_summary.get("transition_count") != len(transitions):
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Motion transition coverage count is inconsistent", field_paths=(f"{coverage_field}.motion_transitions",))

    blueprint = package["reference_blueprint"]
    blueprint_field = f"{field_root}.reference_blueprint"
    require_profile(blueprint, blueprint_field)
    if (
        blueprint.get("artifact_semantics") != "ReferenceBlueprint"
        or blueprint.get("formal_contract_identity") is not None
        or blueprint.get("source_video_id") != source_video_id
    ):
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "ReferenceBlueprint identity or source is invalid", field_paths=(blueprint_field,))
    shared_timeline = _mapping(blueprint.get("shared_timeline"), f"{blueprint_field}.shared_timeline")
    if _string_list(shared_timeline.get("fine_segment_ids"), f"{blueprint_field}.shared_timeline.fine_segment_ids", allow_empty=False) != list(segment_by_id) or _string_list(
        shared_timeline.get("keyframe_ids"), f"{blueprint_field}.shared_timeline.keyframe_ids", allow_empty=False
    ) != list(keyframes):
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "ReferenceBlueprint shared timeline is inconsistent", field_paths=(f"{blueprint_field}.shared_timeline",))
    component_pairs = {
        "motion": motion,
        "narrative": narrative,
        "scene_blocking": scene_map,
        "replication_constraints": constraints,
        "coverage": coverage,
    }
    if any(blueprint.get(name) != expected for name, expected in component_pairs.items()):
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "ReferenceBlueprint components disagree with published artifacts", field_paths=(blueprint_field,))
    return package


def _verify_fine_keyframes_from_source(
    workspace: Path,
    source: Mapping[str, object],
    keyframes: Mapping[str, Mapping[str, object]],
) -> None:
    media = _source_file(workspace, source.get("media_path"), "selected_reference_video.media_path")
    for frame_id, frame in keyframes.items():
        decoded = extract_local_png_frame(media, int(frame["timestamp_ms"]))
        if _digest(decoded) != frame["sha256"]:
            raise SkillError(
                ErrorCode.REFERENCE_MISMATCH,
                "Fine keyframe does not match the selected source video at its timestamp",
                field_paths=(f"analysis_configuration.keyframes.{frame_id}",),
            )


def _shot_evidence(
    beats: list[dict[str, object]], keyframes: dict[str, dict[str, object]], source: dict[str, object], images: dict[str, tuple[int, int, bytes]],
) -> list[dict[str, object]]:
    shots: list[dict[str, object]] = []
    for beat in beats:
        for keyframe_id in beat["keyframe_ids"]:  # type: ignore[union-attr]
            keyframe = keyframes[str(keyframe_id)]
            width, height, _ = images[str(keyframe_id)]
            shots.append({
                "contract_identity": "avp.contract.reference-shot-evidence",
                "contract_version": _VERSION,
                "shot_evidence_id": f"shot-evidence-{keyframe_id}",
                "keyframe_id": keyframe_id,
                "timestamp_ms": keyframe["timestamp_ms"],
                "interval": beat["interval"],
                "beat_id": beat["beat_id"],
                "asset_path": f"keyframes/{keyframe_id}.png",
                "sha256": keyframe["sha256"],
                "width": width,
                "height": height,
                "source_media_sha256": source["sha256"],
                "provenance": {
                    "source_reference_id": source["reference_id"],
                    "source_keyframe_path": keyframe["path"],
                    "timestamp_ms": keyframe["timestamp_ms"],
                },
            })
    return shots


def _reference_beats(beats: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "contract_identity": "avp.contract.reference-beat",
            "contract_version": _VERSION,
            **beat,
        }
        for beat in beats
    ]


def _replication_patterns(beats: list[dict[str, object]], product_id: str) -> list[dict[str, object]]:
    return [
        {
            "contract_identity": "avp.contract.replication-pattern",
            "contract_version": _VERSION,
            "pattern_id": f"pattern-{beat['beat_id']}",
            "interval": beat["interval"],
            "actual_reference_behavior": beat["actual_reference_behavior"],
            "reusable_mechanism": beat["reusable_pattern"],
            "adaptation_to_current_product": beat["product_transfer_suggestion"],
            "adaptation_target_product_id": product_id,
        }
        for beat in beats
    ]


def _asset_record(
    path: str, payload: bytes, role: str, width: int, height: int, provenance: dict[str, object],
) -> dict[str, object]:
    return {
        "asset_path": path,
        "sha256": _digest(payload),
        "byte_size": len(payload),
        "media_type": "image/png",
        "width": width,
        "height": height,
        "role": role,
        "provenance": provenance,
        "provider_execution_input": False,
        "first_frame_eligible": False,
        "product_panel_eligible": False,
    }


def _markdown(artifact: dict[str, object]) -> bytes:
    source = artifact["selected_reference_video"]
    metadata = artifact["video_metadata"]
    lines = [
        "# Reference Storyboard Analysis",
        "",
        f"- Source: {source['source_platform']} / {source['source_id']} / {source['source_url']}",  # type: ignore[index]
        f"- Published: {source['published_at']}",  # type: ignore[index]
        f"- Collected: {source['collected_at']}",  # type: ignore[index]
        f"- Media: {metadata['duration_ms']} ms, {metadata['aspect_ratio']}",  # type: ignore[index]
        f"- Comments: {artifact['comments']['status']}",  # type: ignore[index]
        "",
    ]
    fine_segments = artifact.get("fine_segments")
    if isinstance(fine_segments, list):
        lines.extend(("## Fine segments", ""))
        for segment in fine_segments:
            reasons = ", ".join(
                str(reason.get("reason", "UNAVAILABLE"))
                for reason in segment["segmentation_reasons"]
            )
            lines.extend((
                f"### {segment['segment_id']} ({segment['start_ms']}-{segment['end_ms']} ms)",
                "",
                f"- Duration: {segment['duration_ms']} ms",
                f"- Boundary reasons: {reasons}",
                f"- Previous: {segment['previous_segment_id']}",
                f"- Next: {segment['next_segment_id']}",
                "",
            ))
        lines.extend(("## Segment analysis", ""))
        for analysis in artifact["segment_analysis"]:  # type: ignore[union-attr]
            lines.extend((
                f"### {analysis['segment_id']}",
                "",
                f"- Stage: {analysis['stage_title']}",
                *(
                    f"- {name.replace('_', ' ').title()}: {observation['value']}"
                    for name, observation in analysis["observations"].items()
                ),
                "",
            ))
        lines.extend(("## Core beats", ""))
        for beat in artifact["reference_beats"]:  # type: ignore[union-attr]
            lines.extend((
                f"### {beat['stage_title']} ({beat['start_ms']}-{beat['end_ms']} ms)",
                "",
                f"- Source segments: {', '.join(beat['source_segment_ids'])}",
                f"- Source frames: {', '.join(beat['source_frame_ids'])}",
                f"- Representative frame: {beat['representative_frame_id']}",
                f"- Merge reason: {beat['merge_reason']}",
                f"- Audience psychology: {beat['audience_psychology']}",
                f"- Function: {beat['function_label']}",
                "",
            ))
    for beat in artifact["timeline"]:  # type: ignore[union-attr]
        interval = beat["interval"]
        lines.extend((
            f"## {beat['stage_title']} ({interval['start_ms']}-{interval['end_ms']} ms)",
            "",
            *[f"- {name.replace('_', ' ').title()}: {beat[name]['value']}" for name in _OBSERVATION_FIELDS],
            "",
        ))
    lines.extend(("## Bottom-line formula", "", str(artifact["bottom_line_formula"]["value"]), ""))  # type: ignore[index]
    return "\n".join(lines).encode("utf-8")


def _publish(workspace: Path, files: dict[str, bytes]) -> None:
    target = workspace / _OUTPUT_ROOT
    if target.is_symlink():
        raise SkillError(ErrorCode.PATH_FORBIDDEN, "Output root cannot be a link")
    if target.exists():
        if not target.is_dir():
            raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Output root is not a directory")
        existing = {
            path.relative_to(target).as_posix(): path.read_bytes()
            for path in target.rglob("*")
            if path.is_file()
        }
        if existing == files:
            return
        raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Output root already contains different content")
    stage = Path(tempfile.mkdtemp(prefix=".reference-analysis-", dir=workspace))
    try:
        for relative, payload in files.items():
            destination = stage / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        try:
            os.replace(stage, target)
        except FileExistsError:
            raise SkillError(ErrorCode.OUTPUT_CONFLICT, "A concurrent writer published the output root")
    except SkillError:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        raise SkillError(ErrorCode.WRITE_FAILED, "Storyboard analysis output publication failed") from exc


def analyze_storyboard(request: Mapping[str, object], *, workspace: Path) -> StoryboardAnalysisResult:
    """Analyze one selected reference and publish the canonical evidence artifact set."""
    if not isinstance(request, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Request must be an object")
    normalized_request = {str(key): value for key, value in request.items()}
    forbidden = sorted(set(_forbidden_role_paths(normalized_request)))
    if forbidden:
        raise SkillError(
            ErrorCode.ARTIFACT_ROLE_FORBIDDEN,
            "Reference analysis cannot emit production, first-frame, or Provider execution artifacts",
            field_paths=tuple(forbidden),
        )
    _strict_keys(normalized_request, _TOP_LEVEL_REQUIRED, _TOP_LEVEL_ALLOWED, "request")
    if normalized_request.get("analysis_version") != _VERSION:
        raise SkillError(ErrorCode.VERSION_UNSUPPORTED, "Only storyboard analysis version 1.0.0 is supported", field_paths=("analysis_version",))
    profile = normalized_request.get("analysis_profile", DEFAULT_ANALYSIS_PROFILE)
    if not isinstance(profile, str) or profile not in ANALYSIS_PROFILES:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "analysis_profile is unsupported", field_paths=("analysis_profile",))
    normalized_request["analysis_profile"] = profile
    root = _workspace(workspace)
    source, _ = _validate_source(normalized_request, root)
    metadata = _validate_metadata(normalized_request.get("video_metadata"))
    comments, comment_ids = _validate_comments(normalized_request.get("popular_comments"))
    viral_pack = _validate_viral_pack(normalized_request.get("viral_research_pack"))
    config = _mapping(normalized_request.get("analysis_configuration"), "analysis_configuration")
    _strict_keys(config, _CONFIG_KEYS, _CONFIG_KEYS | _FINE_CONFIG_KEYS | _REPLICATION_CONFIG_KEYS, "analysis_configuration")
    present_fine_keys = set(config) & _FINE_CONFIG_KEYS
    if present_fine_keys and present_fine_keys != _FINE_CONFIG_KEYS:
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "Fine segment analysis fields must be supplied together",
            field_paths=tuple(f"analysis_configuration.{name}" for name in sorted(_FINE_CONFIG_KEYS - present_fine_keys)),
        )
    present_replication_keys = set(config) & _REPLICATION_CONFIG_KEYS
    if present_replication_keys and present_replication_keys != _REPLICATION_CONFIG_KEYS:
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "Replication blueprint fields must be supplied together",
            field_paths=tuple(
                f"analysis_configuration.{name}"
                for name in sorted(_REPLICATION_CONFIG_KEYS - present_replication_keys)
            ),
        )
    current_product = _mapping(config.get("current_product"), "analysis_configuration.current_product")
    product_keys = {"product_id", "category", "display_name"}
    _strict_keys(current_product, product_keys, product_keys, "analysis_configuration.current_product")
    for field in product_keys:
        current_product[field] = _text(current_product.get(field), f"analysis_configuration.current_product.{field}")
    keyframes, keyframe_payloads, keyframe_images = _validate_keyframes(
        config.get("keyframes"), root, int(metadata["duration_ms"]),
    )
    allowed_refs = {"media:selected-reference", "metadata:video", *(f"keyframe:{key}" for key in keyframes), *(f"comment:{key}" for key in comment_ids)}
    if viral_pack is not None:
        allowed_refs.add(f"viral-research-pack:{viral_pack['artifact_ref']}")
    reference_identities = (
        str(source["reference_brand"]),
        str(source["reference_product"]),
        *(str(person) for person in source["reference_people"]),  # type: ignore[union-attr]
    )
    beats, _ = _validate_timeline(
        config.get("timeline"),
        duration_ms=int(metadata["duration_ms"]),
        keyframes=keyframes,
        allowed_refs=allowed_refs,
        reference_identities=reference_identities,
    )
    formula = _observation(
        config.get("bottom_line_formula"),
        "analysis_configuration.bottom_line_formula",
        allowed_refs,
    )
    fine_segments: list[dict[str, object]] = []
    segment_analysis: list[dict[str, object]] = []
    core_beats: list[dict[str, object]] = []
    replication_package: dict[str, dict[str, object]] = {}
    if present_fine_keys:
        fine_media = _source_file(root, source.get("media_path"), "selected_reference_video.media_path")
        audio_available = probe_local_audio_available(fine_media)
        fine_segments, segment_analysis, core_beats = _validate_fine_package(
            config,
            duration_ms=int(metadata["duration_ms"]),
            source_video_id=str(source["source_id"]),
            keyframes=keyframes,
            timeline=beats,
            formula=formula,
            audio_available=audio_available,
        )
        _verify_fine_keyframes_from_source(root, source, keyframes)
        if audio_available:
            allowed_refs.update(f"audio:{segment['segment_id']}" for segment in fine_segments)
    if present_replication_keys:
        replication_package = _validate_replication_package(
            config,
            profile=profile,
            source_video_id=str(source["source_id"]),
            keyframes=keyframes,
            fine_segments=fine_segments,
            segment_analysis=segment_analysis,
        )
    shots = _shot_evidence(beats, keyframes, source, keyframe_images)
    reference_beats = (
        [
            {
                "contract_identity": "avp.contract.reference-beat",
                "contract_version": _VERSION,
                **beat,
            }
            for beat in core_beats
        ]
        if core_beats
        else _reference_beats(beats)
    )
    patterns = _replication_patterns(beats, str(current_product["product_id"]))
    analysis_board = render_analysis_board(
        source,
        metadata,
        beats,
        keyframe_images,
        formula,
        core_beats=core_beats or None,
    )
    shot_board = render_shot_evidence_board(shots, keyframe_images)
    replication_board = render_replication_board(patterns)
    board_payloads = {
        "reference_storyboard_analysis_board.png": analysis_board,
        "shot_evidence_board.png": shot_board,
        "replication_board.png": replication_board,
    }
    role_by_board = {
        "reference_storyboard_analysis_board.png": "reference_storyboard_analysis_board",
        "shot_evidence_board.png": "shot_evidence_board",
        "replication_board.png": "replication_board",
    }
    if replication_package:
        board_payloads["motion_keyframe_atlas.png"] = render_motion_keyframe_atlas(
            replication_package["motion_keyframes"],
            keyframe_images,
        )
        role_by_board["motion_keyframe_atlas.png"] = "motion_keyframe_atlas"
    assets: list[dict[str, object]] = []
    for path, payload in board_payloads.items():
        width, height, _ = decode_png(payload)
        assets.append(_asset_record(
            path, payload, role_by_board[path], width, height,
            {"source_reference_id": source["reference_id"], "request_digest": _digest(_canonical(normalized_request))},
        ))
    for shot in shots:
        keyframe_id = str(shot["keyframe_id"])
        assets.append(_asset_record(
            f"keyframes/{keyframe_id}.png",
            keyframe_payloads[keyframe_id],
            "reference_keyframe_evidence",
            int(shot["width"]),
            int(shot["height"]),
            dict(shot["provenance"]),  # type: ignore[arg-type]
        ))
    board_manifest = {
        "contract_identity": "avp.contract.reference-analysis-board-manifest",
        "contract_version": _VERSION,
        "assets": assets,
    }
    artifact_refs = [
        {"artifact_name": name, "contract_identity": identity, "contract_version": _VERSION, "artifact_ref": reference}
        for name, identity, reference in _CONTRACTS
    ]
    published_blueprint: dict[str, object] | None = None
    if replication_package:
        draft_blueprint = replication_package["reference_blueprint"]
        published_blueprint = {
            **draft_blueprint,
            "shared_timeline": {
                "fine_segment_ids": [segment["segment_id"] for segment in fine_segments],
                "keyframe_ids": list(keyframes),
                "keyframes": [
                    {
                        "frame_id": frame_id,
                        "source_video_id": frame["source_video_id"],
                        "shot_id": frame["shot_id"],
                        "scene_id": frame["scene_id"],
                        "segment_id": frame["segment_id"],
                        "timestamp_ms": frame["timestamp_ms"],
                        "frame_role": frame["frame_role"],
                        "action_roles": frame["action_roles"],
                        "narrative_roles": frame["narrative_roles"],
                        "asset_path": f"keyframes/{frame_id}.png",
                        "sha256": frame["sha256"],
                    }
                    for frame_id, frame in keyframes.items()
                ],
            },
            "artifact_role_restrictions": {
                "provider_execution_input": False,
                "first_frame_eligible": False,
                "production_storyboard": False,
            },
        }
    artifact: dict[str, object] = {
        "contract_identity": "avp.contract.reference-storyboard-analysis",
        "contract_version": _VERSION,
        "analysis_id": f"reference-storyboard-analysis-{_digest(_canonical(normalized_request))[:20]}",
        "analysis_profile": profile,
        "artifact_refs": artifact_refs,
        "selected_reference_video": source,
        "viral_research_pack": viral_pack if viral_pack is not None else {"status": "UNAVAILABLE"},
        "video_metadata": metadata,
        "comments": comments,
        "current_product": current_product,
        "timeline": beats,
        "reference_beats": reference_beats,
        "shot_evidence": shots,
        "replication_patterns": patterns,
        "bottom_line_formula": formula,
        "board_manifest": board_manifest,
        "artifact_role_restrictions": {
            "provider_execution_input": False,
            "first_frame_eligible": False,
            "product_panel_eligible": False,
            "production_storyboard": False,
        },
    }
    if core_beats:
        artifact["fine_segments"] = fine_segments
        artifact["segment_analysis"] = segment_analysis
    if published_blueprint is not None:
        artifact["reference_blueprint"] = published_blueprint
    provenance = {
        "schema_version": _VERSION,
        "analysis_id": artifact["analysis_id"],
        "request_digest": _digest(_canonical(normalized_request)),
        "selected_media_sha256": source["sha256"],
        "selected_media_provenance": source["provenance"],
        "evidence_index": sorted(allowed_refs),
        "artifact_refs": artifact_refs,
        "provider_calls": 0,
        "network_calls": 0,
        "external_upload": False,
    }
    if core_beats:
        provenance["segment_trace"] = [
            {
                "segment_id": segment["segment_id"],
                "start_ms": segment["start_ms"],
                "end_ms": segment["end_ms"],
                "source_video_id": segment["source_video_id"],
                "segmentation_reasons": segment["segmentation_reasons"],
            }
            for segment in fine_segments
        ]
        provenance["frame_trace"] = [
            {
                "frame_id": frame_id,
                "segment_id": frame["segment_id"],
                "shot_id": frame.get("shot_id"),
                "scene_id": frame.get("scene_id"),
                "timestamp_ms": frame["timestamp_ms"],
                "frame_role": frame["frame_role"],
                "action_roles": frame.get("action_roles", []),
                "narrative_roles": frame.get("narrative_roles", []),
                "sha256": frame["sha256"],
                "source_media_sha256": source["sha256"],
                "extraction_method": "local_ffmpeg_frame_decode",
            }
            for frame_id, frame in keyframes.items()
        ]
        provenance["analysis_trace"] = [
            {
                "segment_id": analysis["segment_id"],
                "start_ms": analysis["start_ms"],
                "end_ms": analysis["end_ms"],
                "analysis_provenance": analysis["analysis_provenance"],
                "observations": analysis["observations"],
            }
            for analysis in segment_analysis
        ]
        provenance["beat_trace"] = [
            {
                "beat_id": beat["beat_id"],
                "source_segment_ids": beat["source_segment_ids"],
                "source_frame_ids": beat["source_frame_ids"],
                "representative_frame_id": beat["representative_frame_id"],
            }
            for beat in core_beats
        ]
    if replication_package:
        provenance["blueprint_trace"] = {
            "analysis_profile": profile,
            "source_video_id": source["source_id"],
            "action_ids": [
                chain["action_id"]
                for chain in replication_package["motion_keyframes"]["action_chains"]  # type: ignore[index]
            ],
            "event_ids": [
                event["event_id"]
                for event in replication_package["narrative_event_graph"]["events"]  # type: ignore[index]
            ],
            "scene_ids": [
                scene["scene_id"]
                for scene in replication_package["scene_blocking_map"]["scenes"]  # type: ignore[index]
            ],
        }
    files = {
        "reference_storyboard_analysis.json": _pretty(artifact),
        "reference_storyboard_analysis.md": _markdown(artifact),
        "analysis_provenance.json": _pretty(provenance),
        **board_payloads,
        **{f"keyframes/{keyframe_id}.png": payload for keyframe_id, payload in keyframe_payloads.items()},
    }
    if core_beats:
        files["fine_segments.json"] = _pretty(fine_segments)
        files["segment_analysis.json"] = _pretty(segment_analysis)
    if replication_package and published_blueprint is not None:
        files.update({
            "motion_keyframes.json": _pretty(replication_package["motion_keyframes"]),
            "motion_transitions.json": _pretty(replication_package["motion_transitions"]),
            "narrative_event_graph.json": _pretty(replication_package["narrative_event_graph"]),
            "scene_blocking_map.json": _pretty(replication_package["scene_blocking_map"]),
            "replication_constraints.json": _pretty(replication_package["replication_constraints"]),
            "coverage_report.json": _pretty(replication_package["coverage_report"]),
            "reference_blueprint.json": _pretty(published_blueprint),
        })
    _publish(root, files)
    return StoryboardAnalysisResult(status="COMPLETED", output_root=_OUTPUT_ROOT, artifact=artifact)


__all__ = ["analyze_storyboard"]
