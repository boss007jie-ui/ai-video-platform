"""Deterministic, standard-library storyboard sheet renderer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import re
import struct
import zlib
from typing import Any

from .models import content_digest, snapshot


RENDERER_VERSION = "1.1.0"
LAYOUT_VERSION = "storyboard-master-strip-v2"
MAX_PANELS_PER_PAGE = 9
EXECUTION_POLICY = {
    "role": "human_review_only",
    "first_frame_eligible": False,
    "provider_execution_input": False,
    "semantic_authority": False,
    "ocr_semantic_writeback": False,
}

INK = (20, 22, 25, 255)
MUTED = (89, 94, 102, 255)
PAPER = (250, 250, 249, 255)
WHITE = (255, 255, 255, 255)
RULE = (198, 200, 204, 255)
CAMERA_RED = (204, 43, 48, 255)
SUBJECT_BLUE = (27, 88, 190, 255)


@dataclass(frozen=True, slots=True)
class SheetRenderResult:
    manifest: Mapping[str, Any]
    pages: tuple[bytes, ...]


# Compact 5x7 ASCII font. Keeping the glyphs in the renderer makes output
# deterministic and avoids an optional font/runtime dependency.
_FONT_ROWS: dict[str, tuple[int, ...]] = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "A": (14, 17, 17, 31, 17, 17, 17), "B": (30, 17, 17, 30, 17, 17, 30),
    "C": (14, 17, 16, 16, 16, 17, 14), "D": (30, 17, 17, 17, 17, 17, 30),
    "E": (31, 16, 16, 30, 16, 16, 31), "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (14, 17, 16, 23, 17, 17, 15), "H": (17, 17, 17, 31, 17, 17, 17),
    "I": (14, 4, 4, 4, 4, 4, 14), "J": (7, 2, 2, 2, 18, 18, 12),
    "K": (17, 18, 20, 24, 20, 18, 17), "L": (16, 16, 16, 16, 16, 16, 31),
    "M": (17, 27, 21, 21, 17, 17, 17), "N": (17, 25, 21, 19, 17, 17, 17),
    "O": (14, 17, 17, 17, 17, 17, 14), "P": (30, 17, 17, 30, 16, 16, 16),
    "Q": (14, 17, 17, 17, 21, 18, 13), "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30), "T": (31, 4, 4, 4, 4, 4, 4),
    "U": (17, 17, 17, 17, 17, 17, 14), "V": (17, 17, 17, 17, 17, 10, 4),
    "W": (17, 17, 17, 21, 21, 21, 10), "X": (17, 17, 10, 4, 10, 17, 17),
    "Y": (17, 17, 10, 4, 4, 4, 4), "Z": (31, 1, 2, 4, 8, 16, 31),
    "0": (14, 17, 19, 21, 25, 17, 14), "1": (4, 12, 4, 4, 4, 4, 14),
    "2": (14, 17, 1, 2, 4, 8, 31), "3": (30, 1, 1, 14, 1, 1, 30),
    "4": (2, 6, 10, 18, 31, 2, 2), "5": (31, 16, 16, 30, 1, 1, 30),
    "6": (14, 16, 16, 30, 17, 17, 14), "7": (31, 1, 2, 4, 8, 8, 8),
    "8": (14, 17, 17, 14, 17, 17, 14), "9": (14, 17, 17, 15, 1, 1, 14),
    ".": (0, 0, 0, 0, 0, 6, 6), ",": (0, 0, 0, 0, 6, 6, 4),
    ":": (0, 6, 6, 0, 6, 6, 0), ";": (0, 6, 6, 0, 6, 6, 4),
    "-": (0, 0, 0, 31, 0, 0, 0), "/": (1, 2, 2, 4, 8, 8, 16),
    "(": (2, 4, 8, 8, 8, 4, 2), ")": (8, 4, 2, 2, 2, 4, 8),
    "[": (14, 8, 8, 8, 8, 8, 14), "]": (14, 2, 2, 2, 2, 2, 14),
    "?": (14, 17, 1, 2, 4, 0, 4), "!": (4, 4, 4, 4, 4, 0, 4),
    "'": (4, 4, 2, 0, 0, 0, 0), "\"": (10, 10, 5, 0, 0, 0, 0),
    "&": (12, 18, 20, 8, 21, 18, 13), "+": (0, 4, 4, 31, 4, 4, 0),
    "=": (0, 0, 31, 0, 31, 0, 0), "_": (0, 0, 0, 0, 0, 0, 31),
    "#": (10, 31, 10, 10, 31, 10, 0), "%": (25, 26, 2, 4, 8, 11, 19),
    "<": (2, 4, 8, 16, 8, 4, 2), ">": (8, 4, 2, 1, 2, 4, 8),
}


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _encode_rgba(width: int, height: int, pixels: bytes, text: Mapping[str, str]) -> bytes:
    rows = b"".join(b"\x00" + pixels[y * width * 4 : (y + 1) * width * 4] for y in range(height))
    chunks = [_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))]
    chunks.extend(_chunk(b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("latin-1", "replace")) for key, value in sorted(text.items()))
    chunks.extend((_chunk(b"IDAT", zlib.compress(rows, level=9)), _chunk(b"IEND", b"")))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def _decode_png(data: bytes) -> tuple[int, int, bytes]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Panel asset is not a PNG")
    offset = 8
    width = height = color_type = bit_depth = interlace = None
    compressed = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    if not width or not height or bit_depth != 8 or color_type not in {0, 2, 4, 6} or interlace != 0:
        raise ValueError("Panel PNG format is unsupported")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    stride = width * channels
    raw = zlib.decompress(bytes(compressed))
    previous = bytearray(stride)
    decoded = bytearray()
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        source = raw[cursor : cursor + stride]
        cursor += stride
        row = bytearray(stride)
        for x, value in enumerate(source):
            left = row[x - channels] if x >= channels else 0
            up = previous[x]
            upper_left = previous[x - channels] if x >= channels else 0
            if filter_type == 0:
                result = value
            elif filter_type == 1:
                result = value + left
            elif filter_type == 2:
                result = value + up
            elif filter_type == 3:
                result = value + ((left + up) // 2)
            elif filter_type == 4:
                result = value + _paeth(left, up, upper_left)
            else:
                raise ValueError("Panel PNG filter is unsupported")
            row[x] = result & 0xFF
        decoded.extend(row)
        previous = row
    rgba = bytearray(width * height * 4)
    for index in range(width * height):
        source = index * channels
        target = index * 4
        if color_type == 0:
            rgba[target : target + 4] = bytes((decoded[source], decoded[source], decoded[source], 255))
        elif color_type == 2:
            rgba[target : target + 4] = decoded[source : source + 3] + b"\xff"
        elif color_type == 4:
            rgba[target : target + 4] = bytes((decoded[source], decoded[source], decoded[source], decoded[source + 1]))
        else:
            rgba[target : target + 4] = decoded[source : source + 4]
    return width, height, bytes(rgba)


def _fill(canvas: bytearray, width: int, x: int, y: int, box_width: int, box_height: int, color: tuple[int, int, int, int]) -> None:
    canvas_height = len(canvas) // (width * 4)
    for row in range(max(0, y), min(canvas_height, y + box_height)):
        start = (row * width + max(0, x)) * 4
        end = (row * width + min(width, x + box_width)) * 4
        canvas[start:end] = bytes(color) * ((end - start) // 4)


def _stroke_rect(canvas: bytearray, width: int, x: int, y: int, box_width: int, box_height: int, color: tuple[int, int, int, int], thickness: int = 1) -> None:
    _fill(canvas, width, x, y, box_width, thickness, color)
    _fill(canvas, width, x, y + box_height - thickness, box_width, thickness, color)
    _fill(canvas, width, x, y, thickness, box_height, color)
    _fill(canvas, width, x + box_width - thickness, y, thickness, box_height, color)


def _line(canvas: bytearray, width: int, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int, int], thickness: int = 1, dashed: bool = False) -> None:
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx - dy
    step = 0
    while True:
        if not dashed or (step // max(2, thickness * 2)) % 2 == 0:
            _fill(canvas, width, x0 - thickness // 2, y0 - thickness // 2, thickness, thickness, color)
        if x0 == x1 and y0 == y1:
            break
        twice = 2 * error
        if twice > -dy:
            error -= dy
            x0 += sx
        if twice < dx:
            error += dx
            y0 += sy
        step += 1


def _arrow(canvas: bytearray, width: int, x: int, y: int, length: int, color: tuple[int, int, int, int], direction: str, dashed: bool = False, thickness: int | None = None) -> None:
    vectors = {"right": (1, 0), "left": (-1, 0), "up": (0, -1), "down": (0, 1)}
    dx, dy = vectors.get(direction, (1, 0))
    x1, y1 = x + dx * length, y + dy * length
    thickness = thickness or max(2, length // 16)
    _line(canvas, width, x, y, x1, y1, color, thickness, dashed)
    side = max(5, length // 4)
    if dx:
        _line(canvas, width, x1, y1, x1 - dx * side, y1 - side, color, thickness)
        _line(canvas, width, x1, y1, x1 - dx * side, y1 + side, color, thickness)
    else:
        _line(canvas, width, x1, y1, x1 - side, y1 - dy * side, color, thickness)
        _line(canvas, width, x1, y1, x1 + side, y1 - dy * side, color, thickness)


def _outlined_arrow(canvas: bytearray, width: int, x: int, y: int, length: int, color: tuple[int, int, int, int], direction: str, dashed: bool = False) -> None:
    thickness = max(3, length // 14)
    _arrow(canvas, width, x, y, length, WHITE, direction, dashed, thickness + 4)
    _arrow(canvas, width, x, y, length, color, direction, dashed, thickness)


def _outlined_target(canvas: bytearray, width: int, x: int, y: int, size: int, color: tuple[int, int, int, int]) -> None:
    thickness = max(2, size // 8)
    _stroke_rect(canvas, width, x, y, size, size, WHITE, thickness + 3)
    _stroke_rect(canvas, width, x + 1, y + 1, size - 2, size - 2, color, thickness)
    center_x, center_y = x + size // 2, y + size // 2
    _line(canvas, width, center_x, y - size // 4, center_x, y + size + size // 4, WHITE, thickness + 3)
    _line(canvas, width, x - size // 4, center_y, x + size + size // 4, center_y, WHITE, thickness + 3)
    _line(canvas, width, center_x, y - size // 4, center_x, y + size + size // 4, color, thickness)
    _line(canvas, width, x - size // 4, center_y, x + size + size // 4, center_y, color, thickness)


def _draw_in_frame_annotations(
    canvas: bytearray,
    width: int,
    x: int,
    y: int,
    box_width: int,
    box_height: int,
    camera_motion: str,
    subject_motion: str,
) -> None:
    """Draw compact motion cues over the Panel without covering its center."""

    margin = max(12, min(box_width, box_height) // 18)
    horizontal = max(24, min(box_width // 3, box_height // 5))
    vertical = max(24, min(box_height // 5, box_width // 3))
    camera = camera_motion.lower()
    subject = subject_motion.lower()
    camera_moves = ("push", "pull", "pan", "tilt", "dolly", "orbit", "crane", "rack")

    if "push" in camera:
        top_y = y + margin + horizontal // 4
        _outlined_arrow(canvas, width, x + margin, top_y, horizontal, CAMERA_RED, "right")
        _outlined_arrow(canvas, width, x + box_width - margin, top_y, horizontal, CAMERA_RED, "left")
    elif "pull" in camera:
        center_x = x + box_width // 2
        top_y = y + margin + horizontal // 4
        _outlined_arrow(canvas, width, center_x - margin, top_y, horizontal, CAMERA_RED, "left")
        _outlined_arrow(canvas, width, center_x + margin, top_y, horizontal, CAMERA_RED, "right")
    elif "tilt" in camera or "crane" in camera:
        direction = "down" if "down" in camera else "up"
        start_y = y + margin if direction == "down" else y + margin + vertical
        _outlined_arrow(canvas, width, x + margin, start_y, vertical, CAMERA_RED, direction)
    elif "pan" in camera or "dolly" in camera:
        direction = "left" if "left" in camera else "right"
        start_x = x + box_width - margin if direction == "left" else x + margin
        _outlined_arrow(canvas, width, start_x, y + margin, horizontal, CAMERA_RED, direction)
    elif "orbit" in camera:
        _outlined_arrow(canvas, width, x + margin, y + margin, horizontal, CAMERA_RED, "right")
        _outlined_arrow(canvas, width, x + box_width - margin, y + 2 * margin, horizontal, CAMERA_RED, "left")
    elif "rack" in camera:
        _outlined_target(canvas, width, x + margin, y + margin, max(18, horizontal // 2), CAMERA_RED)
    subject_y = y + box_height // 2
    if any(term in subject for term in ("squeeze", "squash", "compress")):
        center_x = x + box_width // 2
        _outlined_arrow(canvas, width, x + margin, subject_y, horizontal, SUBJECT_BLUE, "right")
        _outlined_arrow(canvas, width, x + box_width - margin, subject_y, horizontal, SUBJECT_BLUE, "left")
    elif any(term in subject for term in ("press", "down", "lower")) and any(term in subject for term in ("lift", "rise", "release")):
        _outlined_arrow(canvas, width, x + box_width - 2 * margin, y + margin, vertical, SUBJECT_BLUE, "down")
        _outlined_arrow(canvas, width, x + margin, y + box_height - margin, vertical, SUBJECT_BLUE, "up")
    elif any(term in subject for term in ("press", "down", "lower")):
        _outlined_arrow(canvas, width, x + box_width - 2 * margin, y + margin, vertical, SUBJECT_BLUE, "down")
    elif any(term in subject for term in ("lift", "rise", "rebound", "up")):
        _outlined_arrow(canvas, width, x + box_width - 2 * margin, y + box_height - margin, vertical, SUBJECT_BLUE, "up")
    elif any(term in subject for term in ("rotate", "turn", "wrist")):
        _outlined_arrow(canvas, width, x + margin, subject_y - margin, horizontal, SUBJECT_BLUE, "right")
        _outlined_arrow(canvas, width, x + box_width - margin, subject_y + margin, horizontal, SUBJECT_BLUE, "left")
    elif any(term in subject for term in ("from right", "withdraw", "exit")):
        _outlined_arrow(canvas, width, x + box_width - margin, subject_y, horizontal, SUBJECT_BLUE, "left")
    elif any(term in subject for term in ("enter", "slide", "push")):
        _outlined_arrow(canvas, width, x + margin, subject_y, horizontal, SUBJECT_BLUE, "right")
    elif subject not in {"", "none"}:
        _outlined_arrow(canvas, width, x + margin, y + box_height - margin, horizontal, SUBJECT_BLUE, "right")


def _blit_fit(canvas: bytearray, canvas_width: int, x: int, y: int, box_width: int, box_height: int, image: tuple[int, int, bytes]) -> None:
    source_width, source_height, pixels = image
    scale = min(box_width / source_width, box_height / source_height)
    target_width = max(1, int(source_width * scale))
    target_height = max(1, int(source_height * scale))
    origin_x = x + (box_width - target_width) // 2
    origin_y = y + (box_height - target_height) // 2
    for target_y in range(target_height):
        source_y = min(source_height - 1, target_y * source_height // target_height)
        for target_x in range(target_width):
            source_x = min(source_width - 1, target_x * source_width // target_width)
            source = (source_y * source_width + source_x) * 4
            target = ((origin_y + target_y) * canvas_width + origin_x + target_x) * 4
            canvas[target : target + 4] = pixels[source : source + 4]


def _ascii(value: object) -> str:
    text = str(value or "").strip().upper()
    replacements = {"\u2013": "-", "\u2014": "-", "\u2192": ">", "\u2190": "<", "\u00b7": "/", "\u2026": "...", "_": " "}
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\s+", " ", text)
    return "".join(character if character in _FONT_ROWS else "?" for character in text)


def _text_width(text: object, scale: int) -> int:
    normalized = _ascii(text)
    return max(0, len(normalized) * 6 * scale - scale)


def _draw_text(canvas: bytearray, width: int, x: int, y: int, text: object, color: tuple[int, int, int, int], scale: int = 2, max_width: int | None = None) -> int:
    normalized = _ascii(text)
    cursor = x
    for character in normalized:
        if max_width is not None and cursor + 5 * scale > x + max_width:
            break
        rows = _FONT_ROWS.get(character, _FONT_ROWS["?"])
        for row_index, bits in enumerate(rows):
            for column in range(5):
                if bits & (1 << (4 - column)):
                    _fill(canvas, width, cursor + column * scale, y + row_index * scale, scale, scale, color)
        cursor += 6 * scale
    return cursor - x


def _ellipsize(text: object, max_width: int, scale: int) -> str:
    normalized = _ascii(text)
    if _text_width(normalized, scale) <= max_width:
        return normalized
    suffix = "..."
    while normalized and _text_width(normalized + suffix, scale) > max_width:
        normalized = normalized[:-1]
    return normalized.rstrip() + suffix if normalized else suffix


def _wrap(text: object, max_width: int, scale: int, max_lines: int) -> list[str]:
    words = _ascii(text).split()
    lines: list[str] = []
    current = ""
    while words and len(lines) < max_lines:
        word = words.pop(0)
        candidate = word if not current else f"{current} {word}"
        if _text_width(candidate, scale) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
            words.insert(0, word)
            continue
        lines.append(_ellipsize(word, max_width, scale))
    if current and len(lines) < max_lines:
        lines.append(current)
    if words and lines:
        remainder = " ".join([lines[-1], *words])
        lines[-1] = _ellipsize(remainder, max_width, scale)
    return lines


def _motion_text(value: object) -> str:
    if isinstance(value, Mapping):
        for key in ("structured_definition", "label", "name", "description"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        annotation = value.get("visual_annotation")
        if isinstance(annotation, Mapping):
            candidate = annotation.get("label")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return "NONE"
    text = str(value or "").strip()
    return text if text and text.lower() != "none" else "NONE"


def _seconds(milliseconds: object) -> str:
    if not isinstance(milliseconds, (int, float)) or isinstance(milliseconds, bool):
        return "?"
    value = milliseconds / 1000
    return str(int(value)) if value.is_integer() else f"{value:.1f}".rstrip("0").rstrip(".")


def _timing_label(entry: Mapping[str, Any]) -> str:
    if entry.get("timing_mode") == "KEYFRAME_ANCHOR":
        return f"{_seconds(entry.get('anchor_time_ms'))}S KEYFRAME"
    return f"{_seconds(entry.get('start_ms'))}-{_seconds(entry.get('end_ms'))}S"


def _aspect_ratio(entry: Mapping[str, Any], master: Mapping[str, Any]) -> tuple[int, int]:
    raw = str(entry.get("aspect_ratio") or master.get("target_aspect_ratio") or "16:9")
    match = re.fullmatch(r"\s*(\d+)\s*:\s*(\d+)\s*", raw)
    if not match:
        return 16, 9
    numerator, denominator = int(match.group(1)), int(match.group(2))
    return (numerator, denominator) if numerator and denominator else (16, 9)


def _framing(entry: Mapping[str, Any], shot: Mapping[str, Any]) -> str:
    explicit = [shot.get(key) for key in ("shot_scale", "framing", "camera_angle", "angle", "viewpoint")]
    values = [str(value).strip() for value in explicit if isinstance(value, str) and value.strip()]
    if values:
        return " / ".join(dict.fromkeys(values))
    motion = _motion_text(entry.get("camera_motion")).lower()
    scale_labels = (
        ("extreme macro", "ECU / MACRO"), ("extreme close", "ECU"),
        ("medium close", "MCU"), ("close-up", "CU"), ("close up", "CU"),
        ("macro", "MACRO"), ("medium", "MEDIUM"), ("wide", "WIDE"),
    )
    angle_labels = (
        ("overhead", "OVERHEAD"), ("eye-level", "EYE LEVEL"), ("eye level", "EYE LEVEL"),
        ("low angle", "LOW ANGLE"), ("high angle", "HIGH ANGLE"),
    )
    found = [next((label for marker, label in scale_labels if marker in motion), "")]
    found.append(next((label for marker, label in angle_labels if marker in motion), ""))
    return " / ".join(label for label in found if label) or "SHOT"


def _camera_instruction(value: object) -> str:
    text = _motion_text(value)
    cleaned = re.sub(r"\b(extreme macro|macro|medium close-up|medium close up|close-up|close up|medium|wide|eye-level|eye level|shallow depth of field)\b", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*,\s*|\s+", " ", cleaned).strip(" ,-/")
    return cleaned or ("STATIC" if any(term in text.lower() for term in ("locked", "static")) else text)


def _action_text(entry: Mapping[str, Any], shot: Mapping[str, Any]) -> str:
    for key in ("action", "action_description", "middle_state", "start_state", "end_state"):
        source = entry.get(key) if key in entry else shot.get(key)
        if isinstance(source, str) and source.strip() and source.strip().lower() != "none":
            return source.strip().rstrip(".") + "."
    return _motion_text(entry.get("subject_motion")).rstrip(".") + "."


def _phase_label(entry: Mapping[str, Any], shot: Mapping[str, Any], index: int, total: int, metadata: Mapping[str, Any]) -> str:
    configured = metadata.get("stage_labels")
    if isinstance(configured, Mapping):
        value = configured.get(str(entry.get("panel_id")), configured.get(str(entry.get("shot_id"))))
        if isinstance(value, str) and value.strip():
            return value.strip()
    conversion = _motion_text(entry.get("conversion_function")).lower()
    action = _action_text(entry, shot).lower()
    if index == 0:
        return "HOOK"
    if index == total - 1 and conversion not in {"none", "proof"}:
        return "CTA"
    if "reveal" in action or conversion not in {"none", "proof"}:
        return "REVEAL"
    if index >= max(1, total - 2):
        return "PAYOFF"
    return "PROOF" if index >= total // 2 else "DEMO"


def _motion_direction(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("left", "pull out", "withdraw", "exits")):
        return "left"
    if any(term in lowered for term in ("up", "lift", "rise", "raises")):
        return "up"
    if any(term in lowered for term in ("down", "press", "lower", "drops")):
        return "down"
    return "right"


def _paginate(entries: list[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    groups: list[list[Mapping[str, Any]]] = []
    for entry in entries:
        if groups and str(groups[-1][-1].get("shot_id")) == str(entry.get("shot_id")):
            groups[-1].append(entry)
        else:
            groups.append([entry])
    pages: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = []
    for group in groups:
        if len(group) > MAX_PANELS_PER_PAGE:
            if current:
                pages.append(current)
                current = []
            pages.extend(group[index : index + MAX_PANELS_PER_PAGE] for index in range(0, len(group), MAX_PANELS_PER_PAGE))
        elif current and len(current) + len(group) > MAX_PANELS_PER_PAGE:
            pages.append(current)
            current = list(group)
        else:
            current.extend(group)
    if current:
        pages.append(current)
    return pages


def _row_counts(panel_count: int, first_aspect: tuple[int, int]) -> tuple[int, ...]:
    if panel_count <= 7 or first_aspect[1] >= first_aspect[0]:
        return (panel_count,)
    first = (panel_count + 1) // 2
    return first, panel_count - first


def _draw_motion_row(canvas: bytearray, width: int, x: int, y: int, max_width: int, label: str, value: str, color: tuple[int, int, int, int], scale: int, dashed: bool) -> None:
    icon_width = max(18, 12 * scale)
    length = max(10, icon_width - 8)
    lowered = value.lower()
    moving_camera_terms = ("push", "pull", "pan", "tilt", "dolly", "orbit", "crane", "rack")
    if label == "CAM" and any(term in lowered for term in ("locked", "static")) and not any(term in lowered for term in moving_camera_terms):
        size = max(9, 6 * scale)
        _stroke_rect(canvas, width, x + (length - size) // 2, y + scale, size, size, color, max(1, scale))
        _fill(canvas, width, x + length // 2, y + 4 * scale, max(1, scale), max(1, scale), color)
    elif any(term in lowered for term in ("squeeze", "squash", "compress")):
        center = x + length // 2
        _arrow(canvas, width, x, y + 4 * scale, length // 2, color, "right", dashed)
        _arrow(canvas, width, x + length, y + 4 * scale, length // 2, color, "left", dashed)
    elif any(term in lowered for term in ("hold", "still", "no release")):
        _line(canvas, width, x, y + 4 * scale, x + length, y + 4 * scale, color, max(1, scale), dashed)
        _line(canvas, width, x, y + 2 * scale, x, y + 6 * scale, color, max(1, scale))
        _line(canvas, width, x + length, y + 2 * scale, x + length, y + 6 * scale, color, max(1, scale))
    else:
        direction = _motion_direction(value)
        if direction == "left":
            arrow_x, arrow_y = x + length, y + 4 * scale
        elif direction == "up":
            arrow_x, arrow_y = x + length // 2, y + length
        else:
            arrow_x, arrow_y = x + length // 2 if direction == "down" else x, y
            arrow_y += 4 * scale if direction == "right" else 0
        _arrow(canvas, width, arrow_x, arrow_y, length, color, direction, dashed)
    text_x = x + icon_width
    _draw_text(canvas, width, text_x, y, f"{label}: {_ellipsize(value, max_width - icon_width, scale)}", color, scale, max_width - icon_width)


def _draw_panel(
    canvas: bytearray,
    width: int,
    master: Mapping[str, Any],
    metadata: Mapping[str, Any],
    entry: Mapping[str, Any],
    shot: Mapping[str, Any],
    decoded: tuple[int, int, bytes],
    x: int,
    y: int,
    slot_width: int,
    row_height: int,
    index: int,
    total: int,
) -> None:
    padding = max(8, slot_width // 28)
    content_width = slot_width - 2 * padding
    scale = 3 if content_width >= 280 else 2 if content_width >= 150 else 1
    line_height = 9 * scale
    info_height = 11 * line_height + padding
    available_image_height = max(90, row_height - info_height - padding)
    ratio_width, ratio_height = _aspect_ratio(entry, master)
    image_width = min(content_width, max(1, available_image_height * ratio_width // ratio_height))
    image_height = min(available_image_height, max(1, image_width * ratio_height // ratio_width))
    image_x = x + (slot_width - image_width) // 2
    _fill(canvas, width, image_x, y, image_width, image_height, (238, 238, 236, 255))
    _blit_fit(canvas, width, image_x, y, image_width, image_height, decoded)
    _draw_in_frame_annotations(
        canvas,
        width,
        image_x,
        y,
        image_width,
        image_height,
        _camera_instruction(entry.get("camera_motion")),
        _motion_text(entry.get("subject_motion")),
    )
    _stroke_rect(canvas, width, image_x, y, image_width, image_height, INK, max(1, scale))

    text_y = y + image_height + padding
    shot_id = str(entry.get("shot_id") or f"S{index + 1:02d}")
    panel_id = str(entry.get("panel_id") or "PANEL")
    _draw_text(canvas, width, x + padding, text_y, _ellipsize(f"{shot_id}  {_timing_label(entry)}", content_width, scale), INK, scale, content_width)
    text_y += line_height
    _draw_text(canvas, width, x + padding, text_y, _ellipsize(panel_id, content_width, max(1, scale - 1)), MUTED, max(1, scale - 1), content_width)
    text_y += line_height
    _draw_text(canvas, width, x + padding, text_y, _ellipsize(_framing(entry, shot), content_width, scale), INK, scale, content_width)
    text_y += line_height + scale

    camera = _camera_instruction(entry.get("camera_motion"))
    subject = _motion_text(entry.get("subject_motion"))
    _draw_motion_row(canvas, width, x + padding, text_y, content_width, "CAM", camera, CAMERA_RED, scale, False)
    text_y += line_height + scale
    _draw_motion_row(canvas, width, x + padding, text_y, content_width, "ACT", subject, SUBJECT_BLUE, scale, True)
    text_y += line_height + 2 * scale

    action_lines = _wrap(_action_text(entry, shot), content_width, scale, 2)
    for line in action_lines:
        _draw_text(canvas, width, x + padding, text_y, line, MUTED, scale, content_width)
        text_y += line_height
    phase = _phase_label(entry, shot, index, total, metadata)
    tag_scale = max(1, scale - 1)
    tag_width = _text_width(phase, tag_scale) + 10 * tag_scale
    tag_height = 9 * tag_scale
    _fill(canvas, width, x + padding, text_y + scale, tag_width, tag_height, INK)
    _draw_text(canvas, width, x + padding + 5 * tag_scale, text_y + 2 * scale, phase, WHITE, tag_scale, tag_width - 10 * tag_scale)


def _header_title(master: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    for key in ("project_name", "product_name", "sku_name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    product = master.get("product_context_bundle")
    if isinstance(product, Mapping):
        value = product.get("product_name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "VIDEO STORYBOARD"


def _total_duration(entries: Sequence[Mapping[str, Any]]) -> str:
    ends = [entry.get("end_ms") for entry in entries if isinstance(entry.get("end_ms"), (int, float)) and not isinstance(entry.get("end_ms"), bool)]
    if ends:
        return f"{_seconds(max(ends))}S"
    durations = [entry.get("duration_ms") for entry in entries if isinstance(entry.get("duration_ms"), (int, float)) and not isinstance(entry.get("duration_ms"), bool)]
    return f"{_seconds(sum(durations))}S" if durations else "DURATION N/A"


def render_storyboard_sheets(
    master: Mapping[str, Any],
    panel_bytes: Mapping[str, bytes],
    metadata: Mapping[str, Any],
) -> SheetRenderResult:
    """Render Master JSON into deterministic horizontal PNG review pages."""

    entries_raw = master.get("master_panel_entries")
    if not isinstance(entries_raw, Sequence) or isinstance(entries_raw, (str, bytes, bytearray)) or not entries_raw:
        raise ValueError("Master requires ordered master_panel_entries")
    entries = [snapshot(item) if isinstance(item, Mapping) else None for item in entries_raw]
    if any(item is None for item in entries):
        raise ValueError("Master Panel entries must be objects")
    typed_entries: list[Mapping[str, Any]] = [item for item in entries if item is not None]
    renderer_code_commit = metadata.get("renderer_code_commit")
    if not isinstance(renderer_code_commit, str) or not renderer_code_commit:
        raise ValueError("renderer_code_commit is required")
    width = int(metadata.get("render_width", 2400))
    height = int(metadata.get("render_height", 1350))
    if width < 1200 or height < 700:
        raise ValueError("Render dimensions are too small")
    font_family = str(metadata.get("font_family", "AVP Storyboard Bitmap"))
    font_fallback = str(metadata.get("font_fallback", "monospace"))
    locale = str(metadata.get("locale", "en-US"))
    master_digest = content_digest(master)
    pages: list[bytes] = []
    page_records: list[dict[str, Any]] = []
    paginated = _paginate(typed_entries)
    shots = master.get("shots")
    shot_by_id = {
        str(shot.get("shot_id")): shot
        for shot in shots
        if isinstance(shots, Sequence) and not isinstance(shots, (str, bytes, bytearray)) and isinstance(shot, Mapping)
    } if isinstance(shots, Sequence) and not isinstance(shots, (str, bytes, bytearray)) else {}
    global_index = {str(entry.get("panel_id")): index for index, entry in enumerate(typed_entries)}

    for page_index, page_entries in enumerate(paginated, 1):
        canvas = bytearray(bytes(PAPER) * width * height)
        margin = max(24, width // 80)
        header_height = max(84, height // 9)
        title_scale = max(2, min(6, width // 480))
        meta_scale = max(1, title_scale - 2)
        title = _header_title(master, metadata)
        platform = str(metadata.get("platform", "VIDEO"))
        aspect = str(master.get("target_aspect_ratio", metadata.get("aspect_ratio", "N/A")))
        version = str(metadata.get("version", master.get("planning_revision", ""))).strip()
        subtitle = f"{platform} / {aspect} / {_total_duration(typed_entries)}"
        if version:
            subtitle += f" / {version if version.upper().startswith('V') else f'V{version}'}"
        _draw_text(canvas, width, margin, max(14, header_height // 7), _ellipsize(title, width - 2 * margin, title_scale), INK, title_scale, width - 2 * margin)
        camera_legend = "CAM CAMERA" if width < 1500 else "CAM CAMERA MOTION"
        subject_legend = "ACT SUBJECT" if width < 1500 else "ACT SUBJECT MOTION"
        legend_width = _text_width(camera_legend, meta_scale) + _text_width(subject_legend, meta_scale) + 82 * meta_scale
        legend_x = max(margin, width - margin - legend_width)
        legend_y = max(14, header_height // 7) + 10 * title_scale
        subtitle_width = max(80, legend_x - margin - 16 * meta_scale)
        _draw_text(canvas, width, margin, legend_y, _ellipsize(subtitle, subtitle_width, meta_scale), MUTED, meta_scale, subtitle_width)
        _arrow(canvas, width, legend_x, legend_y + 4 * meta_scale, 16 * meta_scale, CAMERA_RED, "right")
        camera_text_x = legend_x + 20 * meta_scale
        _draw_text(canvas, width, camera_text_x, legend_y, camera_legend, INK, meta_scale)
        subject_arrow_x = camera_text_x + _text_width(camera_legend, meta_scale) + 20 * meta_scale
        _arrow(canvas, width, subject_arrow_x, legend_y + 4 * meta_scale, 16 * meta_scale, SUBJECT_BLUE, "right", True)
        _draw_text(canvas, width, subject_arrow_x + 20 * meta_scale, legend_y, subject_legend, INK, meta_scale, width - subject_arrow_x - 20 * meta_scale - margin)
        _fill(canvas, width, margin, header_height - 2, width - 2 * margin, 2, INK)
        if len(paginated) > 1:
            page_label = f"SHEET {page_index}/{len(paginated)}"
            page_width = _text_width(page_label, meta_scale)
            _draw_text(canvas, width, width - margin - page_width, max(12, header_height // 7), page_label, MUTED, meta_scale, page_width)

        row_counts = _row_counts(len(page_entries), _aspect_ratio(page_entries[0], master))
        row_gap = max(18, height // 50)
        content_top = header_height + row_gap
        content_height = height - content_top - margin
        row_height = (content_height - row_gap * (len(row_counts) - 1)) // len(row_counts)
        entry_offset = 0
        for row_index, count in enumerate(row_counts):
            available_width = width - 2 * margin
            slot_width = available_width // count
            used_width = slot_width * count
            row_x = margin + (available_width - used_width) // 2
            row_y = content_top + row_index * (row_height + row_gap)
            for column in range(count):
                entry = page_entries[entry_offset + column]
                asset_id = entry.get("panel_asset_id")
                if not isinstance(asset_id, str) or asset_id not in panel_bytes:
                    raise ValueError(f"Panel bytes are missing for {asset_id}")
                decoded = _decode_png(bytes(panel_bytes[asset_id]))
                shot = shot_by_id.get(str(entry.get("shot_id")), {})
                _draw_panel(
                    canvas, width, master, metadata, entry, shot, decoded,
                    row_x + column * slot_width, row_y, slot_width, row_height,
                    global_index.get(str(entry.get("panel_id")), entry_offset + column), len(typed_entries),
                )
            entry_offset += count

        continued_shots: list[str] = []
        if page_index > 1 and str(page_entries[0].get("shot_id")) == str(paginated[page_index - 2][-1].get("shot_id")):
            continued_shots.append(str(page_entries[0].get("shot_id")))
        png = _encode_rgba(
            width,
            height,
            bytes(canvas),
            {
                "Artifact": "VideoGenerationStoryboardMaster Sheet",
                "Authority": "JSON_ONLY",
                "ExecutionPolicy": "HUMAN_REVIEW_ONLY",
                "LayoutVersion": LAYOUT_VERSION,
                "MasterDigest": master_digest,
                "Page": str(page_index),
                "RendererVersion": RENDERER_VERSION,
            },
        )
        pages.append(png)
        page_records.append(
            {
                "page_index": page_index,
                "relative_path": f"storyboard_master_sheet_{page_index:03d}.png",
                "panel_ids": [entry["panel_id"] for entry in page_entries],
                "shot_ids": list(dict.fromkeys(str(entry["shot_id"]) for entry in page_entries)),
                "continued_shot_ids": continued_shots,
                "panel_count": len(page_entries),
                "row_panel_counts": list(row_counts),
                "png_sha256": hashlib.sha256(png).hexdigest(),
                "execution_policy": EXECUTION_POLICY,
                "metadata": {
                    "renderer_version": RENDERER_VERSION,
                    "renderer_code_commit": renderer_code_commit,
                    "layout_version": LAYOUT_VERSION,
                    "font_family": font_family,
                    "font_fallback": font_fallback,
                    "locale": locale,
                    "render_width": width,
                    "render_height": height,
                },
            }
        )
    manifest = snapshot(
        {
            "artifact_name": "StoryboardMasterSheetManifest",
            "schema_version": "1.0.0",
            "master_digest": master_digest,
            "renderer_version": RENDERER_VERSION,
            "renderer_code_commit": renderer_code_commit,
            "layout_version": LAYOUT_VERSION,
            "font_family": font_family,
            "font_fallback": font_fallback,
            "locale": locale,
            "render_width": width,
            "render_height": height,
            "page_count": len(pages),
            "max_panels_per_page": MAX_PANELS_PER_PAGE,
            "execution_policy": EXECUTION_POLICY,
            "pages": page_records,
        }
    )
    return SheetRenderResult(manifest=manifest, pages=tuple(pages))
