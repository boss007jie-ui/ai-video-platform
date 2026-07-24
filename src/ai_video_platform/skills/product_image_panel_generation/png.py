"""Small deterministic PNG renderer for offline fake artifacts."""

from __future__ import annotations

import hashlib
import struct
import zlib


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def deterministic_png(width: int, height: int, *, seed: str) -> bytes:
    """Render a valid solid-color RGB PNG using only the standard library."""

    if width < 1 or height < 1:
        raise ValueError("PNG dimensions must be positive")
    color = hashlib.sha256(seed.encode("utf-8")).digest()[:3]
    scanline = b"\x00" + color * width
    pixels = scanline * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(pixels, 9)) + _chunk(b"IEND", b"")
