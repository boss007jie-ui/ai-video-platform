"""Dependency-free deterministic PNG boards for storyboard analysis."""

from __future__ import annotations

import json
import struct
import unicodedata
import zlib


_FONT = {
    " ": "00000/00000/00000/00000/00000/00000/00000",
    "?": "01110/10001/00001/00010/00100/00000/00100",
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "B": "11110/10001/10001/11110/10001/10001/11110",
    "C": "01111/10000/10000/10000/10000/10000/01111",
    "D": "11110/10001/10001/10001/10001/10001/11110",
    "E": "11111/10000/10000/11110/10000/10000/11111",
    "F": "11111/10000/10000/11110/10000/10000/10000",
    "G": "01111/10000/10000/10111/10001/10001/01111",
    "H": "10001/10001/10001/11111/10001/10001/10001",
    "I": "11111/00100/00100/00100/00100/00100/11111",
    "J": "00111/00010/00010/00010/10010/10010/01100",
    "K": "10001/10010/10100/11000/10100/10010/10001",
    "L": "10000/10000/10000/10000/10000/10000/11111",
    "M": "10001/11011/10101/10101/10001/10001/10001",
    "N": "10001/11001/10101/10011/10001/10001/10001",
    "O": "01110/10001/10001/10001/10001/10001/01110",
    "P": "11110/10001/10001/11110/10000/10000/10000",
    "Q": "01110/10001/10001/10001/10101/10010/01101",
    "R": "11110/10001/10001/11110/10100/10010/10001",
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "T": "11111/00100/00100/00100/00100/00100/00100",
    "U": "10001/10001/10001/10001/10001/10001/01110",
    "V": "10001/10001/10001/10001/10001/01010/00100",
    "W": "10001/10001/10001/10101/10101/10101/01010",
    "X": "10001/10001/01010/00100/01010/10001/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "Z": "11111/00001/00010/00100/01000/10000/11111",
    "0": "01110/10001/10011/10101/11001/10001/01110",
    "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111",
    "3": "11110/00001/00001/01110/00001/00001/11110",
    "4": "00010/00110/01010/10010/11111/00010/00010",
    "5": "11111/10000/10000/11110/00001/00001/11110",
    "6": "01110/10000/10000/11110/10001/10001/01110",
    "7": "11111/00001/00010/00100/01000/01000/01000",
    "8": "01110/10001/10001/01110/10001/10001/01110",
    "9": "01110/10001/10001/01111/00001/00001/01110",
    "-": "00000/00000/00000/11111/00000/00000/00000",
    ".": "00000/00000/00000/00000/00000/01100/01100",
    ",": "00000/00000/00000/00000/00110/00100/01000",
    ":": "00000/01100/01100/00000/01100/01100/00000",
    "/": "00001/00010/00100/01000/10000/00000/00000",
    "+": "00000/00100/00100/11111/00100/00100/00000",
    "_": "00000/00000/00000/00000/00000/00000/11111",
    "@": "01110/10001/10111/10101/10111/10000/01110",
    "#": "01010/01010/11111/01010/11111/01010/01010",
    "(": "00010/00100/01000/01000/01000/00100/00010",
    ")": "01000/00100/00010/00010/00010/00100/01000",
    "'": "00100/00100/00000/00000/00000/00000/00000",
    "=": "00000/11111/00000/11111/00000/00000/00000",
}


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


class _Canvas:
    def __init__(self, width: int, height: int, color: tuple[int, int, int]) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(bytes(color) * width * height)

    def rect(self, x: int, y: int, width: int, height: int, color: tuple[int, int, int]) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + width), min(self.height, y + height)
        row = bytes(color) * max(0, x1 - x0)
        for py in range(y0, y1):
            start = (py * self.width + x0) * 3
            self.pixels[start:start + len(row)] = row

    def text(self, x: int, y: int, value: object, color: tuple[int, int, int], *, scale: int = 2) -> None:
        normalized = unicodedata.normalize("NFKD", str(value)).encode("ascii", "replace").decode("ascii").upper()
        cursor = x
        for char in normalized:
            glyph = _FONT.get(char, _FONT["?"]).split("/")
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit == "1":
                        self.rect(cursor + gx * scale, y + gy * scale, scale, scale, color)
            cursor += 6 * scale

    def lines(
        self, x: int, y: int, value: object, color: tuple[int, int, int], *, max_chars: int, scale: int = 2, max_lines: int = 3,
    ) -> int:
        words = [
            chunk
            for word in str(value).split()
            for chunk in (word[index:index + max_chars] for index in range(0, len(word), max_chars))
        ]
        lines: list[str] = []
        line = ""
        for word in words or [""]:
            candidate = f"{line} {word}".strip()
            if len(candidate) <= max_chars:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = word
            if len(lines) == max_lines:
                break
        if line and len(lines) < max_lines:
            lines.append(line)
        for index, rendered in enumerate(lines):
            self.text(x, y + index * (9 * scale), rendered, color, scale=scale)
        return max(1, len(lines)) * 9 * scale

    def blit(self, image: tuple[int, int, bytes], x: int, y: int, width: int, height: int) -> None:
        source_width, source_height, source = image
        for dy in range(height):
            sy = min(source_height - 1, dy * source_height // height)
            for dx in range(width):
                sx = min(source_width - 1, dx * source_width // width)
                source_start = (sy * source_width + sx) * 3
                target_start = ((y + dy) * self.width + x + dx) * 3
                if 0 <= x + dx < self.width and 0 <= y + dy < self.height:
                    self.pixels[target_start:target_start + 3] = source[source_start:source_start + 3]

    def png(self, metadata: dict[str, object]) -> bytes:
        rows = b"".join(b"\x00" + self.pixels[y * self.width * 3:(y + 1) * self.width * 3] for y in range(self.height))
        layout = json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("latin-1")
        return b"".join((
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)),
            _chunk(b"tEXt", b"avp-layout\x00" + layout),
            _chunk(b"IDAT", zlib.compress(rows, 9)),
            _chunk(b"IEND", b""),
        ))


def decode_png(payload: bytes) -> tuple[int, int, bytes]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    offset = 8
    width = height = color_type = bit_depth = interlace = 0
    compressed = bytearray()
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        kind = payload[offset + 4:offset + 8]
        data = payload[offset + 8:offset + 8 + length]
        if len(data) != length:
            raise ValueError("truncated PNG")
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            break
        offset += length + 12
    channels = {0: 1, 2: 3, 6: 4}.get(color_type)
    if not width or not height or width * height > 50_000_000 or bit_depth != 8 or channels is None or interlace != 0:
        raise ValueError("unsupported PNG layout")
    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    if len(raw) != height * (stride + 1):
        raise ValueError("invalid PNG data length")
    prior = bytearray(stride)
    decoded = bytearray()
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        scanline = bytearray(raw[position + 1:position + 1 + stride])
        position += stride + 1
        for index in range(stride):
            left = scanline[index - channels] if index >= channels else 0
            up = prior[index]
            upper_left = prior[index - channels] if index >= channels else 0
            if filter_type == 1:
                scanline[index] = (scanline[index] + left) & 255
            elif filter_type == 2:
                scanline[index] = (scanline[index] + up) & 255
            elif filter_type == 3:
                scanline[index] = (scanline[index] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                estimate = left + up - upper_left
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
                predictor = (left, up, upper_left)[distances.index(min(distances))]
                scanline[index] = (scanline[index] + predictor) & 255
            elif filter_type != 0:
                raise ValueError("unsupported PNG filter")
        if channels == 1:
            decoded.extend(channel for value in scanline for channel in (value, value, value))
        else:
            decoded.extend(channel for index, channel in enumerate(scanline) if index % channels < 3)
        prior = scanline
    return width, height, bytes(decoded)


_INK = (28, 35, 43)
_MUTED = (79, 91, 105)
_PAPER = (246, 247, 245)
_WHITE = (255, 255, 255)
_ACCENT = (30, 116, 102)
_RED = (185, 62, 68)
_GOLD = (205, 151, 46)


def _label(canvas: _Canvas, x: int, y: int, label: str, value: object, *, width: int = 58) -> int:
    canvas.text(x, y, label, _ACCENT, scale=2)
    return canvas.lines(x, y + 22, value, _INK, max_chars=width, scale=2, max_lines=3) + 30


def render_analysis_board(
    source: dict[str, object], metadata: dict[str, object], beats: list[dict[str, object]], keyframes: dict[str, tuple[int, int, bytes]], formula: dict[str, object],
) -> bytes:
    height = 360 + len(beats) * 590 + 150
    canvas = _Canvas(1800, height, _PAPER)
    canvas.rect(0, 0, 1800, 120, _INK)
    canvas.text(48, 35, "REFERENCE STORYBOARD ANALYSIS", _WHITE, scale=4)
    header = [
        ("SOURCE", f"{source['source_platform']} / {source['source_id']} / {source['source_url']}"),
        ("TIMES", f"PUBLISHED {source['published_at']} / COLLECTED {source['collected_at']}"),
        ("MEDIA", f"{metadata['duration_ms']} MS / {metadata['aspect_ratio']} / {metadata['width']} X {metadata['height']}"),
        ("CATEGORY PRODUCT", f"{source['category']} / {source['reference_product']}"),
    ]
    y = 145
    for label, value in header:
        canvas.text(48, y, label, _ACCENT, scale=2)
        canvas.lines(310, y, value, _INK, max_chars=115, scale=2, max_lines=2)
        y += 48
    field_names = (
        "scene", "shot_scale", "camera_motion", "character_action", "product_action", "product_state", "emotion",
        "audience_psychology", "conversion_function", "viral_mechanism", "comment_evidence", "reusable_pattern", "product_transfer_suggestion",
    )
    for index, beat in enumerate(beats):
        top = 350 + index * 590
        canvas.rect(36, top, 1728, 556, _WHITE)
        canvas.rect(36, top, 14, 556, (_RED, _GOLD)[index % 2])
        interval = beat["interval"]
        canvas.text(72, top + 28, f"{beat['beat_id']} / {interval['start_ms']}-{interval['end_ms']} MS / {beat['stage_title']}", _INK, scale=3)
        left_y = right_y = top + 90
        for field_index, field in enumerate(field_names):
            x = 72 if field_index < 7 else 820
            current_y = left_y if field_index < 7 else right_y
            next_y = current_y + _label(canvas, x, current_y, field.replace("_", " "), beat[field]["value"], width=56)
            if field_index < 7:
                left_y = next_y
            else:
                right_y = next_y
        keyframe_id = beat["keyframe_ids"][0]
        image = keyframes[keyframe_id]
        canvas.rect(1510, top + 88, 210, 328, _INK)
        canvas.blit(image, 1518, top + 96, 194, 312)
        canvas.text(1518, top + 430, keyframe_id, _MUTED, scale=2)
    formula_y = 380 + len(beats) * 590
    canvas.rect(36, formula_y, 1728, 104, _INK)
    canvas.text(66, formula_y + 20, "BOTTOM LINE FORMULA", _GOLD, scale=2)
    canvas.lines(66, formula_y + 53, formula["value"], _WHITE, max_chars=120, scale=2, max_lines=2)
    return canvas.png({
        "board_role": "reference_storyboard_analysis_board",
        "source": source,
        "video_metadata": metadata,
        "required_fields": ["exact intervals", "real keyframes", "stage title", *field_names, "bottom-line formula"],
        "beats": beats,
        "bottom_line_formula": formula,
        "provider_execution_input": False,
        "first_frame_eligible": False,
        "product_panel_eligible": False,
    })


def render_shot_evidence_board(shots: list[dict[str, object]], keyframes: dict[str, tuple[int, int, bytes]]) -> bytes:
    columns = 3
    rows = (len(shots) + columns - 1) // columns
    canvas = _Canvas(1800, 170 + max(1, rows) * 610, _PAPER)
    canvas.rect(0, 0, 1800, 120, _INK)
    canvas.text(48, 35, "SHOT EVIDENCE BOARD", _WHITE, scale=4)
    for index, shot in enumerate(shots):
        column, row = index % columns, index // columns
        x, y = 36 + column * 588, 150 + row * 610
        canvas.rect(x, y, 552, 574, _WHITE)
        canvas.rect(x, y, 552, 12, _ACCENT)
        canvas.text(x + 24, y + 32, shot["keyframe_id"], _INK, scale=3)
        canvas.blit(keyframes[str(shot["keyframe_id"])], x + 24, y + 80, 190, 300)
        provenance = shot["provenance"]
        provenance_text = (
            f"{provenance['source_reference_id']} / {provenance['source_keyframe_path']} / "
            f"{provenance['timestamp_ms']} MS"
        )
        details = (
            ("TIMESTAMP", f"{shot['timestamp_ms']} MS"),
            ("INTERVAL", f"{shot['interval']['start_ms']}-{shot['interval']['end_ms']} MS"),
            ("BEAT", shot["beat_id"]),
            ("SHA256", shot["sha256"][:24]),
            ("SOURCE MEDIA", shot["source_media_sha256"][:24]),
            ("PROVENANCE", provenance_text),
        )
        detail_y = y + 82
        for label, value in details:
            canvas.text(x + 238, detail_y, label, _ACCENT, scale=2)
            canvas.lines(x + 238, detail_y + 22, value, _INK, max_chars=24, scale=2, max_lines=2)
            detail_y += 72
        canvas.text(x + 24, y + 410, "ROLE REFERENCE SHOT EVIDENCE", _MUTED, scale=2)
    return canvas.png({
        "board_role": "shot_evidence_board",
        "shots": shots,
        "provider_execution_input": False,
        "first_frame_eligible": False,
        "product_panel_eligible": False,
    })


def render_replication_board(patterns: list[dict[str, object]]) -> bytes:
    canvas = _Canvas(1800, 220 + len(patterns) * 330, _PAPER)
    canvas.rect(0, 0, 1800, 120, _INK)
    canvas.text(48, 35, "REPLICATION PATTERN BOARD", _WHITE, scale=4)
    columns = ["actual reference behavior", "reusable mechanism", "adaptation to current product"]
    colors = (_RED, _ACCENT, _GOLD)
    for index, (column, color) in enumerate(zip(columns, colors)):
        x = 36 + index * 576
        canvas.rect(x, 145, 552, 54, color)
        canvas.text(x + 18, 164, column, _WHITE, scale=2)
    for row_index, pattern in enumerate(patterns):
        y = 215 + row_index * 330
        values = (
            pattern["actual_reference_behavior"]["value"],
            pattern["reusable_mechanism"]["value"],
            pattern["adaptation_to_current_product"]["value"],
        )
        for column_index, value in enumerate(values):
            x = 36 + column_index * 576
            canvas.rect(x, y, 552, 300, _WHITE)
            canvas.rect(x, y, 8, 300, colors[column_index])
            canvas.text(x + 24, y + 25, f"{pattern['pattern_id']} / {pattern['interval']['start_ms']}-{pattern['interval']['end_ms']} MS", _MUTED, scale=2)
            canvas.lines(x + 24, y + 78, value, _INK, max_chars=28, scale=3, max_lines=7)
            if column_index == 2:
                canvas.text(x + 24, y + 258, f"TARGET {pattern['adaptation_target_product_id']}", _ACCENT, scale=2)
    return canvas.png({
        "board_role": "replication_board",
        "columns": columns,
        "patterns": patterns,
        "provider_execution_input": False,
        "first_frame_eligible": False,
        "product_panel_eligible": False,
    })


__all__ = ["decode_png", "render_analysis_board", "render_replication_board", "render_shot_evidence_board"]
