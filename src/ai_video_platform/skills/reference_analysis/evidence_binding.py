"""Canonical digests that bind prepared visual evidence to finalization requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json


def keyframe_set_digest(keyframes: Sequence[Mapping[str, object]]) -> str:
    """Digest the identity, timestamp, and decoded payload of an exact keyframe set."""
    binding = [
        {
            "keyframe_id": str(frame.get("frame_id", frame.get("keyframe_id"))),
            "sha256": str(frame["sha256"]),
            "timestamp_ms": int(frame["timestamp_ms"]),
        }
        for frame in sorted(
            keyframes,
            key=lambda item: str(item.get("frame_id", item.get("keyframe_id"))),
        )
    ]
    payload = json.dumps(
        binding,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
