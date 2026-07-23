"""Independent JSON helpers and constants for Video Enhancement."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


SCHEMA_VERSION = "0.1.0"
CONTRACT_STATUS = "DRAFT_UNREGISTERED"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def snapshot(value: Any) -> Any:
    def reject_non_finite(item: Any) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("non-finite JSON number")
        if isinstance(item, dict):
            for nested in item.values():
                reject_non_finite(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                reject_non_finite(nested)

    reject_non_finite(value)
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
