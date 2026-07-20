"""Canonical local data helpers for Video Generation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any


SCHEMA_VERSION = "0.1.0"
CONTRACT_STATUS = "DRAFT_UNREGISTERED"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def snapshot(value: object) -> Any:
    return json.loads(canonical_json(value))


def content_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be an RFC 3339 UTC timestamp")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{field} must use UTC")
    return parsed
