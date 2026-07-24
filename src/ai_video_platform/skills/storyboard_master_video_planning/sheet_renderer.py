"""Deterministic, standard-library storyboard sheet renderer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import struct
import zlib
from typing import Any

from .models import content_digest, snapshot


RENDERER_VERSION = "1.0.0"
LAYOUT_VERSION = "storyboard-master-horizontal-v1"
EXECUTION_POLICY = {
    "role": "human_review_only",
    "first_frame_eligible": False,
    "provider_execution_input": False,
    "semantic_authority": False,
    "ocr_semantic_writeback": False,
}


@dataclass(frozen=True, slots=True)
class SheetRenderResult:
    manifest: Mapping[str, Any]
    pages: tuple[bytes, ...]


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
    for row in range(max(0, y), min(len(canvas) // (width * 4), y + box_height)):
        start = (row * width + max(0, x)) * 4
        end = (row * width + min(width, x + box_width)) * 4
        canvas[start:end] = bytes(color) * ((end - start) // 4)


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


def _draw_marker(canvas: bytearray, width: int, x: int, y: int, text: str, subject: bool = False) -> None:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    color = (35, 41, 54, 255) if not subject else (171, 52, 40, 255)
    if subject:
        for offset in range(0, 70, 12):
            _fill(canvas, width, x + offset, y, 7, 5, color)
    else:
        _fill(canvas, width, x, y, 70, 5, color)
    for index, value in enumerate(digest[:16]):
        height = 3 + value % 12
        _fill(canvas, width, x + index * 4, y + 9, 2, height, color)


def _timing_label(entry: Mapping[str, Any]) -> str:
    mode = entry.get("timing_mode")
    if mode == "KEYFRAME_ANCHOR":
        return f"ANCHOR {entry.get('anchor_time_ms')} {entry.get('anchor_role')}"
    return f"SEGMENT {entry.get('start_ms')}-{entry.get('end_ms')} ({entry.get('duration_ms')})"


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
    renderer_code_commit = metadata.get("renderer_code_commit")
    if not isinstance(renderer_code_commit, str) or not renderer_code_commit:
        raise ValueError("renderer_code_commit is required")
    width = int(metadata.get("render_width", 2400))
    height = int(metadata.get("render_height", 1350))
    if width < 1200 or height < 700:
        raise ValueError("Render dimensions are too small")
    font_family = str(metadata.get("font_family", "AVP Bitmap Sans"))
    font_fallback = str(metadata.get("font_fallback", "monospace"))
    locale = str(metadata.get("locale", "en-US"))
    master_digest = content_digest(master)
    pages: list[bytes] = []
    page_records: list[dict[str, Any]] = []
    previous_shot: str | None = None
    for page_index, start in enumerate(range(0, len(entries), 9), 1):
        page_entries = entries[start : start + 9]
        canvas = bytearray(bytes((246, 247, 249, 255)) * width * height)
        _fill(canvas, width, 0, 0, width, 112, (25, 29, 38, 255))
        _fill(canvas, width, 0, height - 160, width, 160, (231, 234, 238, 255))
        cell_width = width // 3
        cell_height = (height - 272) // 3
        continued_shots: list[str] = []
        for cell_index, entry in enumerate(page_entries):
            row, column = divmod(cell_index, 3)
            cell_x = column * cell_width
            cell_y = 112 + row * cell_height
            _fill(canvas, width, cell_x + 8, cell_y + 8, cell_width - 16, cell_height - 16, (255, 255, 255, 255))
            shot_id = str(entry.get("shot_id"))
            if cell_index == 0 and start > 0 and shot_id == previous_shot:
                continued_shots.append(shot_id)
            asset_id = entry.get("panel_asset_id")
            if not isinstance(asset_id, str) or asset_id not in panel_bytes:
                raise ValueError(f"Panel bytes are missing for {asset_id}")
            decoded = _decode_png(bytes(panel_bytes[asset_id]))
            image_height = cell_height - 82
            image_width = min(cell_width // 2, int(image_height * decoded[0] / decoded[1]))
            _fill(canvas, width, cell_x + 20, cell_y + 36, image_width + 4, image_height + 4, (25, 29, 38, 255))
            _blit_fit(canvas, width, cell_x + 22, cell_y + 38, image_width, image_height, decoded)
            marker_x = cell_x + image_width + 44
            _draw_marker(canvas, width, marker_x, cell_y + 55, f"{shot_id}/{entry.get('panel_id')} {_timing_label(entry)}")
            _draw_marker(canvas, width, marker_x, cell_y + 93, str(entry.get("camera_motion", "none")), subject=False)
            _draw_marker(canvas, width, marker_x, cell_y + 131, str(entry.get("subject_motion", "none")), subject=True)
            _draw_marker(canvas, width, marker_x, cell_y + 171, str(entry.get("conversion_function", "none")))
            previous_shot = shot_id
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
        page_sha = hashlib.sha256(png).hexdigest()
        pages.append(png)
        page_records.append(
            {
                "page_index": page_index,
                "relative_path": f"storyboard_master_sheet_{page_index:03d}.png",
                "panel_ids": [entry["panel_id"] for entry in page_entries],
                "shot_ids": list(dict.fromkeys(str(entry["shot_id"]) for entry in page_entries)),
                "continued_shot_ids": continued_shots,
                "panel_count": len(page_entries),
                "png_sha256": page_sha,
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
            "max_panels_per_page": 9,
            "execution_policy": EXECUTION_POLICY,
            "pages": page_records,
        }
    )
    return SheetRenderResult(manifest=manifest, pages=tuple(pages))
