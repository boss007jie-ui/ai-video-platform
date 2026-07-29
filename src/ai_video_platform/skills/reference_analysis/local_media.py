"""Narrow local ffmpeg/ffprobe process seam for the offline Reference owner."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Sequence

from .errors import ErrorCode, SkillError


_ORIGINAL_POPEN = subprocess.Popen
_LOCAL_PROTOCOLS = "file,pipe"
_FORBIDDEN_ARGUMENT_MARKERS = (
    "://",
    "tcp:",
    "udp:",
    "http:",
    "https:",
    "ftp:",
    "sftp:",
    "rtmp:",
    "rtsp:",
)


def resolve_local_media_tool(name: str) -> str:
    if name not in {"ffmpeg", "ffprobe"}:
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Only local ffmpeg and ffprobe are allowed")
    resolved = shutil.which(name)
    if not resolved:
        raise SkillError(
            ErrorCode.MEDIA_INVALID,
            f"Required local media tool is unavailable: {name}",
            field_paths=("video_metadata",),
        )
    return os.fspath(Path(resolved).resolve())


def run_local_media(
    command: Sequence[str],
    *,
    timeout: int,
    text: bool = False,
) -> subprocess.CompletedProcess:
    """Run one validated local media command without enabling a generic subprocess seam."""
    if not command:
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Local media command is empty")
    executable = os.fspath(Path(command[0]).resolve())
    allowed = {resolve_local_media_tool("ffmpeg"), resolve_local_media_tool("ffprobe")}
    if os.path.normcase(executable) not in {os.path.normcase(path) for path in allowed}:
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Local media executable is not allowlisted")
    arguments = [str(argument) for argument in command]
    if any(marker in argument.casefold() for argument in arguments for marker in _FORBIDDEN_ARGUMENT_MARKERS):
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Network-capable media arguments are forbidden")
    if any(argument.startswith((r"\\", "//")) for argument in arguments[1:]):
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Network filesystem media paths are forbidden")
    whitelist_positions = [
        index for index, argument in enumerate(arguments)
        if argument == "-protocol_whitelist" or argument.startswith("-protocol_whitelist=")
    ]
    if len(whitelist_positions) > 1:
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Local media protocol policy cannot be repeated")
    if whitelist_positions:
        position = whitelist_positions[0]
        if (
            arguments[position] != "-protocol_whitelist"
            or position + 1 >= len(arguments)
            or arguments[position + 1] != _LOCAL_PROTOCOLS
        ):
            raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Only local file and pipe media protocols are allowed")
    else:
        arguments[1:1] = ["-protocol_whitelist", _LOCAL_PROTOCOLS]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = _ORIGINAL_POPEN(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        creationflags=creationflags,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise
    return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)


def extract_local_png_frame(media: Path, timestamp_ms: int) -> bytes:
    """Decode one source-video frame at an explicit local timeline position."""
    if timestamp_ms < 0:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local keyframe timestamp is invalid")
    command = [
        resolve_local_media_tool("ffmpeg"),
        "-v", "error",
        "-nostdin",
        "-ss", f"{timestamp_ms / 1000:.3f}",
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
    if completed.returncode != 0 or not isinstance(payload, bytes) or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local keyframe extraction rejected the media")
    return payload


def probe_local_audio_available(media: Path) -> bool:
    """Return whether the selected local video has a first audio stream."""
    command = [
        resolve_local_media_tool("ffprobe"),
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=index",
        "-of", "json",
        os.fspath(media),
    ]
    try:
        completed = run_local_media(command, timeout=30, text=True)
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local audio stream probe failed") from exc
    if completed.returncode != 0 or not isinstance(payload, dict):
        raise SkillError(ErrorCode.MEDIA_INVALID, "Local audio stream probe rejected the media")
    streams = payload.get("streams")
    return isinstance(streams, list) and bool(streams)


__all__ = [
    "extract_local_png_frame",
    "probe_local_audio_available",
    "resolve_local_media_tool",
    "run_local_media",
]
