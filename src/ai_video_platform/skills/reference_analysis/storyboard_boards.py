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
_BLACK = (12, 12, 12)
_CARD = (28, 28, 28)
_ORANGE = (244, 117, 33)
_PALE = (245, 238, 226)

_CJK_TITLE_FONT = {
    "分": (
        "000010000100", "000100001000", "001000010000", "010000100000",
        "100001000000", "000000000000", "111111111110", "000100010000",
        "000100010000", "001000010000", "010000010000", "100000100000",
    ),
    "镜": (
        "010001111100", "111010010000", "010011111100", "010010010000",
        "111011111100", "010000000000", "010011111100", "010010010100",
        "010011111100", "010000100000", "010001001000", "100010000100",
    ),
    "故": (
        "010001001000", "010001001000", "111101111100", "010010010000",
        "011110010000", "010101111100", "010101001000", "010101001000",
        "011001010000", "010001010000", "010010001000", "010100000100",
    ),
    "事": (
        "000010000000", "111111111100", "000010000000", "011111111000",
        "000010001000", "011111111000", "000010000000", "111111111100",
        "000010001000", "011111111000", "000010000000", "000100000000",
    ),
    "板": (
        "001000111100", "001000100000", "111110100000", "001000111100",
        "011000100100", "101000100100", "001001001000", "001001001000",
        "001010010000", "001010010000", "001100001000", "001000000100",
    ),
}


def _cjk_text(
    canvas: _Canvas,
    x: int,
    y: int,
    value: str,
    color: tuple[int, int, int],
    *,
    scale: int,
) -> int:
    cursor = x
    for character in value:
        glyph = _CJK_TITLE_FONT[character]
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    canvas.rect(cursor + gx * scale, y + gy * scale, scale, scale, color)
        cursor += 14 * scale
    return cursor


def _label(canvas: _Canvas, x: int, y: int, label: str, value: object, *, width: int = 58) -> int:
    canvas.text(x, y, label, _ACCENT, scale=2)
    return canvas.lines(x, y + 22, value, _INK, max_chars=width, scale=2, max_lines=3) + 30


def render_analysis_board(
    source: dict[str, object],
    metadata: dict[str, object],
    beats: list[dict[str, object]],
    keyframes: dict[str, tuple[int, int, bytes]],
    formula: dict[str, object],
    *,
    core_beats: list[dict[str, object]] | None = None,
) -> bytes:
    display_beats = core_beats or [
        {
            "beat_id": beat["beat_id"],
            "start_ms": beat["interval"]["start_ms"],
            "end_ms": beat["interval"]["end_ms"],
            "representative_frame_id": beat["keyframe_ids"][0],
            "stage_title": beat["stage_title"],
            "visual_summary": beat["scene"]["value"],
            "key_action": beat["character_action"]["value"],
            "audience_psychology": beat["audience_psychology"]["value"],
            "viral_or_conversion_function": beat["conversion_function"]["value"],
            "function_label": beat["viral_mechanism"]["value"],
        }
        for beat in beats
    ]
    count = len(display_beats)
    canvas = _Canvas(3000, 1500, _BLACK)
    canvas.rect(0, 0, 3000, 12, _ORANGE)
    title_end = _cjk_text(canvas, 60, 38, "分镜故事板", _ORANGE, scale=3)
    canvas.text(title_end + 14, 54, "/ STORYBOARD", _PALE, scale=4)
    canvas.text(60, 126, "REFERENCE VIDEO ANALYSIS", _ORANGE, scale=2)
    canvas.lines(
        60,
        158,
        f"TOPIC {source['category']}   PLATFORM {source['source_platform']}   FORMAT {metadata['aspect_ratio']}   DURATION {metadata['duration_ms']} MS",
        _PALE,
        max_chars=145,
        scale=2,
        max_lines=1,
    )

    gap = 24
    left = 60
    available = 2880
    card_width = (available - gap * max(0, count - 1)) // max(1, count)
    card_top = 225
    card_height = 1000
    for index, beat in enumerate(display_beats):
        x = left + index * (card_width + gap)
        canvas.rect(x, card_top, card_width, card_height, _CARD)
        canvas.rect(x, card_top, card_width, 10, _ORANGE)
        canvas.text(x + 20, card_top + 28, f"{index + 1:02d}", _ORANGE, scale=4)
        canvas.text(
            x + min(130, card_width // 3),
            card_top + 36,
            f"{beat['start_ms']}-{beat['end_ms']} MS",
            _PALE,
            scale=2,
        )
        image_x = x + 20
        image_y = card_top + 95
        image_width = card_width - 40
        canvas.rect(image_x - 4, image_y - 4, image_width + 8, 408, _ORANGE)
        canvas.blit(keyframes[str(beat["representative_frame_id"])], image_x, image_y, image_width, 400)
        text_width = max(12, (card_width - 40) // 18)
        y = card_top + 535
        canvas.lines(x + 20, y, beat["stage_title"], _PALE, max_chars=text_width, scale=3, max_lines=2)
        y += 76
        details = (
            ("VISUAL", beat["visual_summary"]),
            ("ACTION", beat["key_action"]),
            ("PSYCHOLOGY", beat["audience_psychology"]),
            ("ROLE", beat["viral_or_conversion_function"]),
        )
        for label, value in details:
            canvas.text(x + 20, y, label, _ORANGE, scale=2)
            y += 25
            y += canvas.lines(x + 20, y, value, _PALE, max_chars=text_width, scale=2, max_lines=2) + 22
        canvas.rect(x + 20, card_top + 934, card_width - 40, 44, _ORANGE)
        canvas.lines(
            x + 32,
            card_top + 946,
            beat["function_label"],
            _BLACK,
            max_chars=max(10, text_width - 2),
            scale=2,
            max_lines=1,
        )

    footer_y = 1280
    canvas.rect(60, footer_y, 2880, 150, _CARD)
    canvas.rect(60, footer_y, 12, 150, _ORANGE)
    canvas.text(96, footer_y + 28, "CORE FORMULA", _ORANGE, scale=3)
    canvas.lines(96, footer_y + 78, formula["value"], _PALE, max_chars=145, scale=3, max_lines=2)
    return canvas.png({
        "board_role": "reference_storyboard_analysis_board",
        "title": "分镜故事板 / Storyboard",
        "theme": "black-orange",
        "layout": "horizontal-core-beat-cards",
        "source": source,
        "video_metadata": metadata,
        "required_fields": ["exact intervals", "real representative frames", "stage title", "visual", "action", "audience psychology", "function", "bottom-line formula"],
        "beats": display_beats,
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
