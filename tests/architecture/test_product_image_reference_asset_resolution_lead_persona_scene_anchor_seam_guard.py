from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from ai_video_platform.core.continuity_review import (
    IMAGE_MAX_BYTES,
    IMAGE_MAX_EDGE,
    ReferenceImageError,
    load_ref_image_paths_by_ids,
)


def _png(path: Path, width: int, height: int) -> None:
    kind = b"IHDR"
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(header)) + kind + header + struct.pack(">I", zlib.crc32(kind + header) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk)


class ProductImageReferenceAssetResolutionSeamGuardTests(unittest.TestCase):
    def test_reference_resolution_is_id_based_ordered_and_locally_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.png"
            second = root / "second.png"
            _png(first, 64, 64)
            _png(second, 32, 128)

            resolved = load_ref_image_paths_by_ids(
                [{"reference_id": "first", "path": first}, {"reference_id": "second", "path": second}],
                ("second", "first"),
            )

        self.assertEqual(resolved, (second, first))
        self.assertEqual(IMAGE_MAX_EDGE, 1792)
        self.assertEqual(IMAGE_MAX_BYTES, 3 * 1024 * 1024)

    def test_reference_resolution_rejects_unknown_ids_before_consume(self) -> None:
        with self.assertRaisesRegex(ReferenceImageError, "was not found"):
            load_ref_image_paths_by_ids({}, ("unknown",))


if __name__ == "__main__":
    unittest.main()
