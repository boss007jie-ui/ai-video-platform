"""Effective-period semantics shared by facts, assets, and rules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping


def _parse_utc(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("timestamp must use UTC Z form")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp must use UTC")
    return parsed


def is_effective(period: Mapping[str, str] | None, at: str) -> bool:
    """Return whether ``at`` is within the half-open effective period."""

    if not period:
        return True
    instant = _parse_utc(at)
    valid_from = period.get("valid_from")
    valid_until = period.get("valid_until")
    if valid_from is not None and instant < _parse_utc(valid_from):
        return False
    if valid_until is not None and instant >= _parse_utc(valid_until):
        return False
    return True
