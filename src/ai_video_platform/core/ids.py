"""Identity helpers with an RFC 9562-compatible UUIDv7 implementation."""

from __future__ import annotations

import secrets
import time
import uuid


def uuid7(*, timestamp_ms: int | None = None, random_bits: int | None = None) -> uuid.UUID:
    timestamp_ms = int(time.time_ns() // 1_000_000) if timestamp_ms is None else timestamp_ms
    if not 0 <= timestamp_ms < 1 << 48:
        raise ValueError("timestamp_ms must fit in 48 bits")
    random_bits = secrets.randbits(74) if random_bits is None else random_bits
    if not 0 <= random_bits < 1 << 74:
        raise ValueError("random_bits must fit in 74 bits")

    random_a = random_bits >> 62
    random_b = random_bits & ((1 << 62) - 1)
    integer = timestamp_ms << 80
    integer |= 0x7 << 76
    integer |= random_a << 64
    integer |= 0b10 << 62
    integer |= random_b
    return uuid.UUID(int=integer)


def is_uuid7(value: uuid.UUID | str) -> bool:
    parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    return parsed.version == 7 and parsed.variant == uuid.RFC_4122
