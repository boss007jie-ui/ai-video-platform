"""Deterministic local boundary detection and fine-segment construction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import re
import subprocess

from .errors import ErrorCode, SkillError
from .local_media import resolve_local_media_tool, run_local_media


_SILENCE_PATTERN = re.compile(r"silence_(?:start|end):\s*([0-9]+(?:\.[0-9]+)?)")


def _run_local(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
    try:
        return run_local_media(command, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local boundary detection failed") from exc


def _ffmpeg() -> str:
    return resolve_local_media_tool("ffmpeg")


def scan_visual_change_evidence(
    media: Path,
    duration_ms: int,
    *,
    sampling_fps: int,
) -> list[dict[str, object]]:
    """Return every non-zero local RGB transition for bounded coverage rescans."""
    width = height = 32
    completed = _run_local(
        [
            _ffmpeg(),
            "-v", "error",
            "-nostdin",
            "-protocol_whitelist", "file,pipe",
            "-i", os.fspath(media),
            "-vf", f"fps={sampling_fps},scale={width}:{height}",
            "-pix_fmt", "rgb24",
            "-f", "rawvideo",
            "pipe:1",
        ],
        timeout=60,
    )
    if completed.returncode != 0:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local visual boundary detection rejected the media")
    frame_size = width * height * 3
    payload = completed.stdout
    frame_count = len(payload) // frame_size
    if frame_count < 1 or len(payload) % frame_size:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local visual boundary samples are incomplete")
    frames = [payload[index * frame_size : (index + 1) * frame_size] for index in range(frame_count)]
    signals: list[dict[str, object]] = []
    for index, (previous, current) in enumerate(zip(frames, frames[1:]), start=1):
        score = sum(abs(left - right) for left, right in zip(previous, current)) / (frame_size * 255)
        timestamp_ms = round(index * 1000 / sampling_fps)
        if score > 0 and 0 < timestamp_ms < duration_ms:
            signals.append({
                "timestamp_ms": timestamp_ms,
                "reasons": ["visual_frame_change"],
                "evidence": {"method": "local_rgb_frame_difference", "score": round(score, 6)},
            })
    return signals


def _visual_signals(
    media: Path,
    duration_ms: int,
    *,
    sampling_fps: int,
    threshold: float,
    visual_evidence: Sequence[Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    evidence = (
        scan_visual_change_evidence(media, duration_ms, sampling_fps=sampling_fps)
        if visual_evidence is None
        else visual_evidence
    )
    return [
        dict(signal)
        for signal in evidence
        if float(signal.get("evidence", {}).get("score", 0.0)) >= threshold  # type: ignore[union-attr]
    ]


def _audio_signals(media: Path, duration_ms: int) -> list[dict[str, object]]:
    completed = _run_local(
        [
            _ffmpeg(),
            "-hide_banner",
            "-nostdin",
            "-protocol_whitelist", "file,pipe",
            "-i", os.fspath(media),
            "-af", "silencedetect=noise=-35dB:d=0.18",
            "-f", "null",
            "-",
        ],
        timeout=60,
    )
    stderr = completed.stderr.decode("utf-8", errors="replace")
    signals: list[dict[str, object]] = []
    for match in _SILENCE_PATTERN.finditer(stderr):
        timestamp_ms = round(float(match.group(1)) * 1000)
        if 0 < timestamp_ms < duration_ms:
            signals.append({
                "timestamp_ms": timestamp_ms,
                "reasons": ["audio_section_change"],
                "evidence": {"method": "local_ffmpeg_silencedetect"},
            })
    return signals


def detect_boundary_signals(
    media: Path,
    duration_ms: int,
    policy: Mapping[str, object],
    *,
    visual_evidence: Sequence[Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Return ordered local visual/audio boundary evidence without network access."""
    sampling_fps = int(policy["sampling_fps"])
    threshold = float(policy["visual_change_threshold"])
    signals = _visual_signals(
        media,
        duration_ms,
        sampling_fps=sampling_fps,
        threshold=threshold,
        visual_evidence=visual_evidence,
    )
    if bool(policy["enable_audio_boundaries"]):
        signals.extend(_audio_signals(media, duration_ms))
    return sorted(signals, key=lambda signal: (int(signal["timestamp_ms"]), str(signal["reasons"])))


def _reason_records(signal: Mapping[str, object]) -> list[dict[str, object]]:
    raw_reasons = signal.get("reasons")
    if not isinstance(raw_reasons, Sequence) or isinstance(raw_reasons, (str, bytes, bytearray)):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Boundary reasons must be an array")
    evidence = signal.get("evidence")
    records: list[dict[str, object]] = []
    for reason in raw_reasons:
        if not isinstance(reason, str) or not reason.strip():
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Boundary reason is invalid")
        records.append({"reason": reason.strip(), "evidence": evidence})
    if not records:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Boundary reasons cannot be empty")
    return records


def build_fine_segments(
    source_video_id: str,
    duration_ms: int,
    signals: Sequence[Mapping[str, object]],
    min_segment_ms: int,
) -> list[dict[str, object]]:
    """Coalesce nearby signals and return an exact contiguous source timeline."""
    candidates: list[tuple[int, list[dict[str, object]]]] = []
    for signal in sorted(signals, key=lambda item: int(item.get("timestamp_ms", -1))):
        raw_timestamp = signal.get("timestamp_ms")
        if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, int):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Boundary timestamp must be an integer")
        if raw_timestamp <= 0 or raw_timestamp >= duration_ms:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Boundary timestamp is outside the video")
        reasons = _reason_records(signal)
        if candidates and raw_timestamp - candidates[-1][0] < min_segment_ms:
            candidates[-1][1].extend(reasons)
        else:
            candidates.append((raw_timestamp, reasons))
    if candidates and duration_ms - candidates[-1][0] < min_segment_ms:
        candidates.pop()

    boundaries = [(0, [{"reason": "video_start", "evidence": {"method": "source_timeline"}}]), *candidates]
    segments: list[dict[str, object]] = []
    for index, (start_ms, reasons) in enumerate(boundaries):
        end_ms = boundaries[index + 1][0] if index + 1 < len(boundaries) else duration_ms
        segment_id = f"segment-{index + 1:03d}"
        segments.append({
            "segment_id": segment_id,
            "source_video_id": source_video_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_ms": end_ms - start_ms,
            "segmentation_reasons": reasons,
            "previous_segment_id": f"segment-{index:03d}" if index else None,
            "next_segment_id": f"segment-{index + 2:03d}" if index + 1 < len(boundaries) else None,
        })
    return segments


__all__ = [
    "build_fine_segments",
    "detect_boundary_signals",
    "scan_visual_change_evidence",
]
