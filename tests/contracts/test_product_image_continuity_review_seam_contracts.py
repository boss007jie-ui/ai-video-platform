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
    assemble_continuity_review,
    consume_continuity_review,
    load_ref_image_paths_by_ids,
)


def _png(path: Path, width: int, height: int, payload: bytes = b"pixel") -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", payload)
        + chunk(b"IEND", b"")
    )


class ProductImageContinuityReviewSeamContractTests(unittest.TestCase):
    def test_assembly_consumption_preserves_fields_and_reference_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.png"
            second = root / "second.png"
            _png(first, 120, 80)
            _png(second, 80, 120)

            assembly = assemble_continuity_review(
                sources={"ref-1": first, "ref-2": second},
                reference_ids=("ref-2", "ref-1"),
                narrative_mode="narrative-led",
                lead_persona_ids=("persona-1",),
                scene_anchor_ids=("anchor-1", "anchor-2"),
            )
            consumed = consume_continuity_review(assembly)

        self.assertEqual(consumed.reference_image_paths, (second, first))
        self.assertEqual(consumed.narrative_mode, "narrative-led")
        self.assertEqual(consumed.lead_persona_ids, ("persona-1",))
        self.assertEqual(consumed.scene_anchor_ids, ("anchor-1", "anchor-2"))

    def test_loader_rejects_missing_non_image_over_edge_and_over_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            non_image = root / "not-image.bin"
            non_image.write_bytes(b"plain text")
            over_edge = root / "over-edge.png"
            _png(over_edge, IMAGE_MAX_EDGE + 1, 1)
            over_bytes = root / "over-bytes.png"
            _png(over_bytes, 1, 1, b"x" * (IMAGE_MAX_BYTES + 1))

            cases = (
                ({}, ("missing",), "was not found"),
                ({"bad": non_image}, ("bad",), "PNG or JPEG"),
                ({"edge": over_edge}, ("edge",), "IMAGE_MAX_EDGE"),
                ({"bytes": over_bytes}, ("bytes",), "IMAGE_MAX_BYTES"),
            )
            for sources, reference_ids, message in cases:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(ReferenceImageError, message):
                        load_ref_image_paths_by_ids(sources, reference_ids)


if __name__ == "__main__":
    unittest.main()
