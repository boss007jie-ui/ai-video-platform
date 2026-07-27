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
from .models import StoryboardAnalysisResult
from .storyboard_boards import decode_png, render_analysis_board, render_replication_board, render_shot_evidence_board


_VERSION = "1.0.0"
_OUTPUT_ROOT = "reference_analysis"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_REQUIRED = {"analysis_version", "selected_reference_video", "video_metadata", "analysis_configuration"}
_TOP_LEVEL_ALLOWED = _TOP_LEVEL_REQUIRED | {"viral_research_pack", "popular_comments"}
_CONFIG_KEYS = {"current_product", "keyframes", "timeline", "bottom_line_formula"}
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
    for index, raw in enumerate(value):
        field = f"analysis_configuration.keyframes[{index}]"
        record = _mapping(raw, field)
        keys = {"keyframe_id", "timestamp_ms", "path", "sha256"}
        _strict_keys(record, keys, keys, field)
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
    root = _workspace(workspace)
    source, _ = _validate_source(normalized_request, root)
    metadata = _validate_metadata(normalized_request.get("video_metadata"))
    comments, comment_ids = _validate_comments(normalized_request.get("popular_comments"))
    viral_pack = _validate_viral_pack(normalized_request.get("viral_research_pack"))
    config = _mapping(normalized_request.get("analysis_configuration"), "analysis_configuration")
    _strict_keys(config, _CONFIG_KEYS, _CONFIG_KEYS, "analysis_configuration")
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
    shots = _shot_evidence(beats, keyframes, source, keyframe_images)
    reference_beats = _reference_beats(beats)
    patterns = _replication_patterns(beats, str(current_product["product_id"]))
    analysis_board = render_analysis_board(source, metadata, beats, keyframe_images, formula)
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
    artifact: dict[str, object] = {
        "contract_identity": "avp.contract.reference-storyboard-analysis",
        "contract_version": _VERSION,
        "analysis_id": f"reference-storyboard-analysis-{_digest(_canonical(normalized_request))[:20]}",
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
    provenance = {
        "schema_version": _VERSION,
        "analysis_id": artifact["analysis_id"],
        "request_digest": _digest(_canonical(normalized_request)),
        "selected_media_sha256": source["sha256"],
        "selected_media_provenance": source["provenance"],
        "evidence_index": sorted(allowed_refs),
        "artifact_refs": artifact_refs,
        "provider_calls": 0,
    }
    files = {
        "reference_storyboard_analysis.json": _pretty(artifact),
        "reference_storyboard_analysis.md": _markdown(artifact),
        "analysis_provenance.json": _pretty(provenance),
        **board_payloads,
        **{f"keyframes/{keyframe_id}.png": payload for keyframe_id, payload in keyframe_payloads.items()},
    }
    _publish(root, files)
    return StoryboardAnalysisResult(status="COMPLETED", output_root=_OUTPUT_ROOT, artifact=artifact)


__all__ = ["analyze_storyboard"]
