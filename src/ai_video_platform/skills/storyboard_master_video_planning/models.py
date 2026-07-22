"""Deterministic JSON helpers for unregistered local draft artifacts."""

from __future__ import annotations

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
