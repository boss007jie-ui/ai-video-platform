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
from .models import ReferenceBreakdownDraftResult
from .storyboard import _mapping, _strict_keys, _text, _validate_metadata, _validate_source, _workspace


_VERSION = "1.0.0"
_MODE = "local_draft_v1"
_OUTPUT_ROOT = "reference_breakdown_draft"
_REQUEST_REQUIRED = {"analysis_version", "mode", "selected_reference_video"}
_REQUEST_ALLOWED = _REQUEST_REQUIRED | {"video_metadata", "current_product", "policy"}
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
    resolved = shutil.which(name)
    if not resolved:
        raise SkillError(
            ErrorCode.MEDIA_INVALID,
            f"Required local media tool is unavailable: {name}",
            field_paths=("video_metadata",),
        )
    return resolved


def _probe_metadata(media: Path) -> dict[str, object]:
    command = [
        _local_tool("ffprobe"),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,duration:format=duration",
        "-of", "json",
        os.fspath(media),
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
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
        *seek,
        "-i", os.fspath(media),
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "png",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
            check=False,
        )
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
        relative = Path(str(keyframe.get("path")))
        path = workspace / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not path.is_file()
            or _digest(path.read_bytes()) != keyframe.get("sha256")
        ):
            raise SkillError(ErrorCode.OUTPUT_CONFLICT, "Draft keyframe content changed")
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
    _strict_keys(normalized, _REQUEST_REQUIRED, _REQUEST_ALLOWED, "request")
    if normalized.get("analysis_version") != _VERSION:
        raise SkillError(
            ErrorCode.VERSION_UNSUPPORTED,
            "Only local draft analysis version 1.0.0 is supported",
            field_paths=("analysis_version",),
        )
    if normalized.get("mode") != _MODE:
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Only mode=local_draft_v1 is allowed", field_paths=("mode",))
    root = _workspace(workspace)
    request_digest = _digest(_canonical(normalized))
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
