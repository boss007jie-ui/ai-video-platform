"""Offline preparation of non-executable local reference breakdown drafts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .errors import ErrorCode, SkillError
from .fine_segments import build_fine_segments, detect_boundary_signals
from .local_media import resolve_local_media_tool, run_local_media
from .models import ReferenceBreakdownDraftResult
from .segment_storyboard import build_segment_analysis, derive_core_beats, derive_formula
from .storyboard import _mapping, _strict_keys, _text, _validate_metadata, _validate_source, _workspace


_VERSION = "1.0.0"
_MODE = "local_draft_v1"
_FINE_MODE = "local_fine_segments_v1"
_OUTPUT_ROOT = "reference_breakdown_draft"
_REQUEST_REQUIRED = {"analysis_version", "mode", "selected_reference_video"}
_REQUEST_ALLOWED = _REQUEST_REQUIRED | {"video_metadata", "current_product", "policy"}
_FINE_ALLOWED = _REQUEST_REQUIRED | {
    "video_metadata", "current_product", "segmentation_policy", "offline_analysis",
}
_POLICY_KEYS = {"interval_ms", "max_keyframes"}
_PRODUCT_KEYS = {"product_id", "category", "display_name"}
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
_FORBIDDEN_INPUT_KEYS = {
    "cloud_video_llm", "cloud_mode", "provider", "provider_request", "upload", "external_upload",
}


def _number(value: object, field: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required number is invalid", field_paths=(field,))
    return float(value)


def _fine_policy(value: object) -> dict[str, object]:
    if value is None:
        return {
            "sampling_fps": 4,
            "visual_change_threshold": 0.22,
            "min_segment_ms": 250,
            "enable_audio_boundaries": True,
        }
    policy = _mapping(value, "segmentation_policy")
    keys = {"sampling_fps", "visual_change_threshold", "min_segment_ms", "enable_audio_boundaries"}
    _strict_keys(policy, keys, keys, "segmentation_policy")
    enabled = policy.get("enable_audio_boundaries")
    if not isinstance(enabled, bool):
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "enable_audio_boundaries must be a boolean",
            field_paths=("segmentation_policy.enable_audio_boundaries",),
        )
    return {
        "sampling_fps": _integer(policy.get("sampling_fps"), "segmentation_policy.sampling_fps", minimum=1, maximum=30),
        "visual_change_threshold": _number(
            policy.get("visual_change_threshold"),
            "segmentation_policy.visual_change_threshold",
            minimum=0.0,
            maximum=1.0,
        ),
        "min_segment_ms": _integer(
            policy.get("min_segment_ms"), "segmentation_policy.min_segment_ms", minimum=1,
        ),
        "enable_audio_boundaries": enabled,
    }


def _offline_analysis(value: object) -> dict[str, object]:
    if value is None:
        return {
            "analyzer_id": "UNAVAILABLE",
            "boundary_signals": [],
            "segment_annotations": [],
        }
    analysis = _mapping(value, "offline_analysis")
    keys = {"analyzer_id", "boundary_signals", "segment_annotations"}
    _strict_keys(analysis, keys, keys, "offline_analysis")
    analyzer_id = _text(analysis.get("analyzer_id"), "offline_analysis.analyzer_id")
    signals = analysis.get("boundary_signals")
    annotations = analysis.get("segment_annotations")
    if not isinstance(signals, list) or not isinstance(annotations, list):
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "Offline signals and annotations must be arrays",
            field_paths=("offline_analysis",),
        )
    normalized_signals: list[dict[str, object]] = []
    for index, raw in enumerate(signals):
        field = f"offline_analysis.boundary_signals[{index}]"
        signal = _mapping(raw, field)
        signal_keys = {"timestamp_ms", "reasons", "evidence"}
        _strict_keys(signal, signal_keys, signal_keys, field)
        timestamp_ms = _integer(signal.get("timestamp_ms"), f"{field}.timestamp_ms", minimum=1)
        reasons = signal.get("reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(reason, str) or not reason for reason in reasons):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Boundary reasons must be a non-empty array", field_paths=(f"{field}.reasons",))
        normalized_signals.append({
            "timestamp_ms": timestamp_ms,
            "reasons": list(reasons),
            "evidence": signal.get("evidence"),
        })
    return {"analyzer_id": analyzer_id, "boundary_signals": normalized_signals, "segment_annotations": annotations}


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pretty(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _integer(value: object, field: str, *, minimum: int, maximum: int | None = None) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required integer is invalid", field_paths=(field,))
    return value


def _forbidden_paths(value: object, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            path = f"{prefix}.{raw_key}" if prefix else str(raw_key)
            if key in _FORBIDDEN_INPUT_KEYS:
                findings.append(path)
            findings.extend(_forbidden_paths(nested, path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            findings.extend(_forbidden_paths(nested, f"{prefix}[{index}]"))
    return findings


def _local_tool(name: str) -> str:
    return resolve_local_media_tool(name)


def _probe_metadata(media: Path) -> dict[str, object]:
    command = [
        _local_tool("ffprobe"),
        "-v", "error",
        "-protocol_whitelist", "file,pipe",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,duration:format=duration",
        "-of", "json",
        os.fspath(media),
    ]
    try:
        completed = run_local_media(command, timeout=30, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local video metadata probe failed") from exc
    if completed.returncode != 0:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local video metadata probe rejected the media")
    try:
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        duration_ms = int(round(float(stream.get("duration") or payload["format"]["duration"]) * 1000))
        width = int(stream["width"])
        height = int(stream["height"])
        codec = str(stream["codec_name"])
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local video metadata is incomplete") from exc
    if duration_ms < 1 or width < 1 or height < 1 or not codec:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local video metadata is invalid")
    divisor = math.gcd(width, height)
    return {
        "duration_ms": duration_ms,
        "width": width,
        "height": height,
        "aspect_ratio": f"{width // divisor}:{height // divisor}",
        "media_type": "video/mp4",
        "codec": codec,
    }


def _policy(value: object) -> dict[str, int]:
    if value is None:
        return {"interval_ms": 2000, "max_keyframes": 12}
    policy = _mapping(value, "policy")
    _strict_keys(policy, set(), _POLICY_KEYS, "policy")
    return {
        "interval_ms": _integer(policy.get("interval_ms", 2000), "policy.interval_ms", minimum=1),
        "max_keyframes": _integer(
            policy.get("max_keyframes", 12),
            "policy.max_keyframes",
            minimum=1,
            maximum=12,
        ),
    }


def _current_product(value: object) -> dict[str, str]:
    if value is None:
        return {
            "product_id": "current-product-unavailable",
            "category": "UNAVAILABLE",
            "display_name": "UNAVAILABLE",
        }
    product = _mapping(value, "current_product")
    _strict_keys(product, _PRODUCT_KEYS, _PRODUCT_KEYS, "current_product")
    return {field: _text(product.get(field), f"current_product.{field}") for field in sorted(_PRODUCT_KEYS)}


def _timestamps(duration_ms: int, policy: Mapping[str, int]) -> list[int]:
    timestamps = list(range(0, duration_ms, int(policy["interval_ms"])))
    near_end = duration_ms - 1
    if near_end not in timestamps:
        timestamps.append(near_end)
    if len(timestamps) > int(policy["max_keyframes"]):
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "Requested interval exceeds the allowed keyframe count",
            field_paths=("policy",),
        )
    return timestamps


def _observation(name: str, keyframe_id: str) -> dict[str, object]:
    if name == "comment_evidence":
        return {"value": "DRAFT: UNAVAILABLE; no comment evidence was supplied.", "evidence_refs": []}
    descriptions = {
        "scene": "sequence placeholder; scene content is not visually confirmed",
        "shot_scale": "shot scale is not visually confirmed",
        "camera_motion": "camera motion is not visually confirmed",
        "character_action": "character action is not visually confirmed",
        "product_action": "product action is not visually confirmed",
        "product_state": "product state is not visually confirmed",
        "emotion": "emotion is not visually confirmed",
        "audience_psychology": "audience response is not visually confirmed",
        "conversion_function": "conversion function is not visually confirmed",
        "viral_mechanism": "viral mechanism is not visually confirmed",
        "actual_reference_behavior": "reference behavior is not visually confirmed",
        "reusable_pattern": "reusable pattern requires human visual review",
        "product_transfer_suggestion": "adapt only after human visual review; no reference identity is copied",
    }
    return {
        "value": f"DRAFT: {descriptions[name]}.",
        "evidence_refs": [f"keyframe:{keyframe_id}"],
    }


def _timeline(timestamps: list[int], duration_ms: int) -> list[dict[str, object]]:
    beats: list[dict[str, object]] = []
    for index, timestamp in enumerate(timestamps):
        keyframe_id = f"kf-{index + 1:03d}"
        end = timestamps[index + 1] if index + 1 < len(timestamps) else duration_ms
        beat: dict[str, object] = {
            "beat_id": f"beat-{index + 1:03d}",
            "start_ms": timestamp,
            "end_ms": end,
            "stage_title": f"DRAFT: interval {index + 1}; metadata/sequence template, not visually confirmed",
            "keyframe_ids": [keyframe_id],
        }
        beat.update({name: _observation(name, keyframe_id) for name in _OBSERVATION_FIELDS})
        beats.append(beat)
    return beats


def _extract_keyframe(media: Path, timestamp_ms: int, *, near_end: bool) -> bytes:
    seek = ["-sseof", "-0.100"] if near_end else ["-ss", f"{timestamp_ms / 1000:.3f}"]
    command = [
        _local_tool("ffmpeg"),
        "-v", "error",
        "-nostdin",
        "-protocol_whitelist", "file,pipe",
        *seek,
        "-i", os.fspath(media),
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "png",
        "pipe:1",
    ]
    try:
        completed = run_local_media(command, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local keyframe extraction failed") from exc
    payload = completed.stdout
    if completed.returncode != 0 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local keyframe extraction rejected the media")
    return payload


def _published_replay(workspace: Path, request_digest: str) -> ReferenceBreakdownDraftResult | None:
    target = workspace / _OUTPUT_ROOT
    if not target.exists():
        return None
    if not target.is_dir() or target.is_symlink():
        raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Draft output root already exists with a conflicting type")
    try:
        manifest = json.loads((target / "draft_manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Draft output root contains different content") from exc
    if manifest.get("request_digest") != request_digest:
        raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Draft output root contains different content")
    for keyframe in manifest.get("keyframes", []):
        relative = Path(str(keyframe.get("path") or keyframe.get("asset_path")))
        path = workspace / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not path.is_file()
            or _digest(path.read_bytes()) != keyframe.get("sha256")
        ):
            raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Draft keyframe content changed")
    return ReferenceBreakdownDraftResult(status="COMPLETED", output_root=_OUTPUT_ROOT, artifact=manifest)


def _prepare_fine_breakdown(
    normalized: dict[str, object],
    *,
    root: Path,
    request_digest: str,
) -> ReferenceBreakdownDraftResult:
    replay = _published_replay(root, request_digest)
    if replay is not None:
        return replay
    source, _ = _validate_source({"selected_reference_video": normalized["selected_reference_video"]}, root)
    if str(source["source_platform"]).casefold() != "local":
        raise SkillError(
            ErrorCode.SCOPE_FORBIDDEN,
            "local_fine_segments_v1 accepts only explicitly selected local media",
            field_paths=("selected_reference_video.source_platform",),
        )
    media = root / str(source["media_path"])
    if "video_metadata" in normalized:
        metadata = _validate_metadata(normalized["video_metadata"])
        metadata_source = "caller_supplied"
    else:
        metadata = _probe_metadata(media)
        metadata_source = "local_ffprobe"
    policy = _fine_policy(normalized.get("segmentation_policy"))
    offline = _offline_analysis(normalized.get("offline_analysis"))
    local_signals = detect_boundary_signals(media, int(metadata["duration_ms"]), policy)
    signals = [*local_signals, *offline["boundary_signals"]]  # type: ignore[list-item]
    segments = build_fine_segments(
        str(source["source_id"]),
        int(metadata["duration_ms"]),
        signals,
        int(policy["min_segment_ms"]),
    )
    stage = Path(tempfile.mkdtemp(prefix=f".{_OUTPUT_ROOT}-stage-", dir=root))
    target = root / _OUTPUT_ROOT
    keyframes: list[dict[str, object]] = []
    keyframe_dir = stage / "keyframes"
    keyframe_dir.mkdir()
    for segment in segments:
        start_ms = int(segment["start_ms"])
        end_ms = int(segment["end_ms"])
        timestamps = {
            "start": start_ms,
            "representative": start_ms + ((end_ms - start_ms) // 2),
            "end": end_ms - 1,
        }
        for role, timestamp_ms in timestamps.items():
            frame_id = f"{segment['segment_id']}-{role}"
            filename = f"{frame_id}.png"
            payload = _extract_keyframe(
                media,
                timestamp_ms,
                near_end=timestamp_ms == int(metadata["duration_ms"]) - 1,
            )
            (keyframe_dir / filename).write_bytes(payload)
            keyframes.append({
                "frame_id": frame_id,
                "source_video_id": source["source_id"],
                "segment_id": segment["segment_id"],
                "timestamp_ms": timestamp_ms,
                "frame_role": role,
                "asset_path": f"{_OUTPUT_ROOT}/keyframes/{filename}",
                "sha256": _digest(payload),
            })
    segment_analysis = build_segment_analysis(
        segments,
        keyframes,
        offline["segment_annotations"],  # type: ignore[arg-type]
        analyzer_id=str(offline["analyzer_id"]),
    )
    core_beats = derive_core_beats(segments, segment_analysis, keyframes)
    formula = derive_formula(core_beats)
    analysis_by_segment = {str(item["segment_id"]): item for item in segment_analysis}
    timeline: list[dict[str, object]] = []
    for beat in core_beats:
        first_analysis = analysis_by_segment[str(beat["source_segment_ids"][0])]  # type: ignore[index]
        observations = first_analysis["observations"]
        representative = str(beat["representative_frame_id"])

        def observed(name: str) -> dict[str, object]:
            value = str(observations[name]["value"])  # type: ignore[index]
            return {
                "value": value,
                "evidence_refs": [] if value == "UNAVAILABLE" else [f"keyframe:{representative}"],
            }

        conversion = observed("conversion_function")
        conversion_value = str(conversion["value"])
        timeline.append({
            "beat_id": beat["beat_id"],
            "start_ms": beat["start_ms"],
            "end_ms": beat["end_ms"],
            "stage_title": beat["stage_title"],
            "keyframe_ids": list(beat["source_frame_ids"]),
            "scene": observed("scene"),
            "shot_scale": observed("shot_scale_and_camera_position"),
            "camera_motion": observed("camera_motion"),
            "character_action": observed("primary_subject_action"),
            "product_action": observed("product_action_and_state"),
            "product_state": observed("product_action_and_state"),
            "emotion": observed("emotion_change"),
            "audience_psychology": observed("audience_psychology"),
            "conversion_function": conversion,
            "viral_mechanism": observed("viral_mechanism"),
            "comment_evidence": {"value": "UNAVAILABLE", "evidence_refs": []},
            "actual_reference_behavior": observed("narrative_function"),
            "reusable_pattern": observed("viral_mechanism"),
            "product_transfer_suggestion": {
                "value": (
                    "UNAVAILABLE"
                    if conversion_value == "UNAVAILABLE"
                    else f"Adapt the category-level {conversion_value} mechanism to the current product."
                ),
                "evidence_refs": [] if conversion_value == "UNAVAILABLE" else [f"keyframe:{representative}"],
            },
        })
    publication_formula = {
        "value": formula["value"],
        "evidence_refs": [f"keyframe:{beat['representative_frame_id']}" for beat in core_beats],
    }
    current_product = _current_product(normalized.get("current_product"))
    analyze_request = {
        "analysis_version": _VERSION,
        "selected_reference_video": source,
        "video_metadata": metadata,
        "analysis_configuration": {
            "current_product": current_product,
            "keyframes": [
                {
                    "keyframe_id": frame["frame_id"],
                    "source_video_id": frame["source_video_id"],
                    "segment_id": frame["segment_id"],
                    "timestamp_ms": frame["timestamp_ms"],
                    "frame_role": frame["frame_role"],
                    "path": frame["asset_path"],
                    "sha256": frame["sha256"],
                }
                for frame in keyframes
            ],
            "timeline": timeline,
            "bottom_line_formula": publication_formula,
            "fine_segments": segments,
            "segment_analysis": segment_analysis,
            "core_beats": core_beats,
        },
    }
    manifest = {
        "draft": True,
        "draft_version": _FINE_MODE,
        "analysis_version": _VERSION,
        "request_digest": request_digest,
        "method_provenance": {
            "mode": _FINE_MODE,
            "metadata_strategy": metadata_source,
            "boundary_detector": "local_ffmpeg_plus_offline_signals",
            "offline_analyzer_id": offline["analyzer_id"],
            "visual_confirmation": "OFFLINE_EVIDENCE_ONLY",
        },
        "network_calls": 0,
        "provider_calls": 0,
        "external_upload": False,
        "executable": False,
        "source_video": {"media_path": source["media_path"], "sha256": source["sha256"]},
        "segmentation_policy": policy,
        "fine_segment_count": len(segments),
        "keyframes": keyframes,
        "artifacts": [
            "draft_manifest.json",
            "fine_segments.json",
            "keyframes/index.json",
            "segment_analysis.json",
            "draft_core_beats.json",
            "draft_timeline.json",
            "draft_bottom_line_formula.json",
            "analyze_storyboard_request.json",
        ],
    }
    try:
        (stage / "fine_segments.json").write_bytes(_pretty(segments))
        (keyframe_dir / "index.json").write_bytes(_pretty(keyframes))
        (stage / "segment_analysis.json").write_bytes(_pretty(segment_analysis))
        (stage / "draft_core_beats.json").write_bytes(_pretty(core_beats))
        (stage / "draft_timeline.json").write_bytes(_pretty(timeline))
        (stage / "draft_bottom_line_formula.json").write_bytes(_pretty(formula))
        (stage / "analyze_storyboard_request.json").write_bytes(_pretty(analyze_request))
        (stage / "draft_manifest.json").write_bytes(_pretty(manifest))
        try:
            os.replace(stage, target)
        except FileExistsError as exc:
            raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Draft output was concurrently published") from exc
    except SkillError:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        raise SkillError(ErrorCode.WRITE_FAILED, "Fine-segment draft publication failed") from exc
    return ReferenceBreakdownDraftResult(status="COMPLETED", output_root=_OUTPUT_ROOT, artifact=manifest)


def prepare_reference_breakdown(
    request: Mapping[str, object], *, workspace: Path,
) -> ReferenceBreakdownDraftResult:
    """Prepare a local-only draft package consumable by analyze-storyboard."""
    if not isinstance(request, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Request must be an object")
    normalized = {str(key): value for key, value in request.items()}
    forbidden = sorted(set(_forbidden_paths(normalized)))
    if forbidden:
        raise SkillError(
            ErrorCode.SCOPE_FORBIDDEN,
            "Local draft preparation cannot use cloud video LLMs, Providers, or uploads",
            field_paths=tuple(forbidden),
        )
    mode = normalized.get("mode")
    allowed = _FINE_ALLOWED if mode == _FINE_MODE else _REQUEST_ALLOWED
    _strict_keys(normalized, _REQUEST_REQUIRED, allowed, "request")
    if normalized.get("analysis_version") != _VERSION:
        raise SkillError(
            ErrorCode.VERSION_UNSUPPORTED,
            "Only local draft analysis version 1.0.0 is supported",
            field_paths=("analysis_version",),
        )
    root = _workspace(workspace)
    request_digest = _digest(_canonical(normalized))
    if mode == _FINE_MODE:
        return _prepare_fine_breakdown(normalized, root=root, request_digest=request_digest)
    if mode != _MODE:
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Only mode=local_draft_v1 is allowed", field_paths=("mode",))
    replay = _published_replay(root, request_digest)
    if replay is not None:
        return replay
    source, _ = _validate_source({"selected_reference_video": normalized["selected_reference_video"]}, root)
    if str(source["source_platform"]).casefold() != "local":
        raise SkillError(
            ErrorCode.SCOPE_FORBIDDEN,
            "local_draft_v1 accepts only explicitly selected local media",
            field_paths=("selected_reference_video.source_platform",),
        )
    media = root / str(source["media_path"])
    if "video_metadata" in normalized:
        metadata = _validate_metadata(normalized["video_metadata"])
        metadata_source = "caller_supplied"
    else:
        metadata = _probe_metadata(media)
        metadata_source = "local_ffprobe"
    policy = _policy(normalized.get("policy"))
    timestamps = _timestamps(int(metadata["duration_ms"]), policy)
    current_product = _current_product(normalized.get("current_product"))
    timeline = _timeline(timestamps, int(metadata["duration_ms"]))
    stage = Path(tempfile.mkdtemp(prefix=f".{_OUTPUT_ROOT}-stage-", dir=root))
    target = root / _OUTPUT_ROOT
    try:
        keyframe_dir = stage / "keyframes"
        keyframe_dir.mkdir()
        keyframes: list[dict[str, object]] = []
        for index, timestamp_ms in enumerate(timestamps):
            keyframe_id = f"kf-{index + 1:03d}"
            filename = f"{keyframe_id}.png"
            payload = _extract_keyframe(
                media,
                timestamp_ms,
                near_end=timestamp_ms == int(metadata["duration_ms"]) - 1,
            )
            (keyframe_dir / filename).write_bytes(payload)
            keyframes.append({
                "keyframe_id": keyframe_id,
                "timestamp_ms": timestamp_ms,
                "path": f"{_OUTPUT_ROOT}/keyframes/{filename}",
                "sha256": _digest(payload),
            })
        formula = {
            "value": "DRAFT: sequence template only; bottom-line formula requires human visual review.",
            "evidence_refs": ["media:selected-reference", *(f"keyframe:{item['keyframe_id']}" for item in keyframes)],
        }
        analyze_request = {
            "analysis_version": _VERSION,
            "selected_reference_video": source,
            "video_metadata": metadata,
            "analysis_configuration": {
                "current_product": current_product,
                "keyframes": keyframes,
                "timeline": timeline,
                "bottom_line_formula": formula,
            },
        }
        manifest = {
            "draft": True,
            "draft_version": _MODE,
            "analysis_version": _VERSION,
            "request_digest": request_digest,
            "method_provenance": {
                "mode": _MODE,
                "metadata_strategy": metadata_source,
                "keyframe_extractor": "local_ffmpeg",
                "text_strategy": "metadata_sequence_template",
                "visual_confirmation": "NOT_PERFORMED",
            },
            "provider_calls": 0,
            "external_upload": False,
            "executable": False,
            "source_video": {"media_path": source["media_path"], "sha256": source["sha256"]},
            "policy": policy,
            "keyframes": keyframes,
            "artifacts": [
                "draft_manifest.json",
                "keyframes/index.json",
                "draft_timeline.json",
                "draft_bottom_line_formula.json",
                "analyze_storyboard_request.json",
            ],
        }
        (keyframe_dir / "index.json").write_bytes(_pretty(keyframes))
        (stage / "draft_timeline.json").write_bytes(_pretty(timeline))
        (stage / "draft_bottom_line_formula.json").write_bytes(_pretty(formula))
        (stage / "analyze_storyboard_request.json").write_bytes(_pretty(analyze_request))
        (stage / "draft_manifest.json").write_bytes(_pretty(manifest))
        try:
            os.replace(stage, target)
        except FileExistsError as exc:
            raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Draft output was concurrently published") from exc
    except SkillError:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        raise SkillError(ErrorCode.WRITE_FAILED, "Draft output publication failed") from exc
    return ReferenceBreakdownDraftResult(status="COMPLETED", output_root=_OUTPUT_ROOT, artifact=manifest)


__all__ = ["prepare_reference_breakdown"]
