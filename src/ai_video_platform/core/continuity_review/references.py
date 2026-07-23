"""Offline reference-image resolution and hard media limits."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeAlias


IMAGE_MAX_EDGE = 1792
IMAGE_MAX_BYTES = 3 * 1024 * 1024

ReferenceSource: TypeAlias = Mapping[str, Any] | Sequence[Mapping[str, Any]]


class ReferenceImageError(ValueError):
    """Raised when a local reference image cannot pass continuity-review gates."""


def _source_path(value: object, reference_id: str) -> Path:
    if isinstance(value, (str, Path)):
        return Path(value)
    if isinstance(value, Mapping):
        for key in ("path", "local_path"):
            candidate = value.get(key)
            if isinstance(candidate, (str, Path)):
                return Path(candidate)
        raise ReferenceImageError(
            f"Reference image '{reference_id}' must provide a local path"
        )
    raise ReferenceImageError(
        f"Reference image '{reference_id}' must provide a local path"
    )


def _normalise_sources(sources: ReferenceSource) -> dict[str, Path]:
    if isinstance(sources, Mapping):
        return {
            str(reference_id): _source_path(value, str(reference_id))
            for reference_id, value in sources.items()
        }

    index: dict[str, Path] = {}
    for item in sources:
        if not isinstance(item, Mapping):
            raise ReferenceImageError("Reference records must be mappings")
        reference_id = item.get("reference_id")
        if not isinstance(reference_id, str) or not reference_id.strip():
            raise ReferenceImageError("Reference records require a non-empty reference_id")
        if reference_id in index:
            raise ReferenceImageError(f"Duplicate reference_id '{reference_id}'")
        index[reference_id] = _source_path(item, reference_id)
    return index


def _jpeg_dimensions(path: Path, data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset + 3 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            break
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        } and segment_length >= 7:
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return width, height
        offset += segment_length
    raise ReferenceImageError(f"Reference image '{path}' has invalid JPEG dimensions")


def _image_dimensions(path: Path, data: bytes) -> tuple[int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height
    jpeg = _jpeg_dimensions(path, data)
    if jpeg is not None:
        return jpeg
    raise ReferenceImageError(
        f"Reference image '{path}' must be a readable PNG or JPEG image"
    )


def _validate_image(reference_id: str, path: Path) -> Path:
    if not path.exists() or not path.is_file():
        raise ReferenceImageError(
            f"Reference image '{reference_id}' does not exist at local path '{path}'"
        )
    byte_size = path.stat().st_size
    if byte_size > IMAGE_MAX_BYTES:
        raise ReferenceImageError(
            f"Reference image '{reference_id}' exceeds IMAGE_MAX_BYTES={IMAGE_MAX_BYTES} bytes"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReferenceImageError(
            f"Reference image '{reference_id}' could not be read from '{path}'"
        ) from exc
    width, height = _image_dimensions(path, data)
    if width <= 0 or height <= 0:
        raise ReferenceImageError(
            f"Reference image '{reference_id}' has invalid dimensions {width}x{height}"
        )
    if max(width, height) > IMAGE_MAX_EDGE:
        raise ReferenceImageError(
            f"Reference image '{reference_id}' exceeds IMAGE_MAX_EDGE={IMAGE_MAX_EDGE}: {width}x{height}"
        )
    return path


def load_ref_image_paths_by_ids(
    sources: ReferenceSource,
    reference_ids: Iterable[str],
) -> tuple[Path, ...]:
    """Resolve approved local reference paths in caller-requested order."""

    index = _normalise_sources(sources)
    resolved: list[Path] = []
    for reference_id in reference_ids:
        if not isinstance(reference_id, str) or not reference_id.strip():
            raise ReferenceImageError("reference_ids must contain non-empty strings")
        path = index.get(reference_id)
        if path is None:
            raise ReferenceImageError(
                f"Reference image id '{reference_id}' was not found in the local reference index"
            )
        resolved.append(_validate_image(reference_id, path))
    return tuple(resolved)


__all__ = [
    "IMAGE_MAX_BYTES",
    "IMAGE_MAX_EDGE",
    "ReferenceImageError",
    "ReferenceSource",
    "load_ref_image_paths_by_ids",
]
