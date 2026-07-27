from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import prepare_reference_breakdown

from tests.skills.reference_analysis.fine_segment_fixture import ten_segment_request


class PrepareFineSegmentTests(unittest.TestCase):
    def test_prepare_fine_mode_creates_contiguous_content_driven_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = ten_segment_request(workspace)

            result = prepare_reference_breakdown(request, workspace=workspace)

            root = workspace / result.output_root
            segments = json.loads((root / "fine_segments.json").read_text(encoding="utf-8"))
            self.assertEqual(len(segments), 10)
            self.assertEqual(segments[0]["start_ms"], 0)
            self.assertEqual(segments[-1]["end_ms"], 4000)
            self.assertTrue(
                all(left["end_ms"] == right["start_ms"] for left, right in zip(segments, segments[1:]))
            )
            self.assertTrue(all(segment["segmentation_reasons"] for segment in segments[1:]))
            self.assertEqual(segments[0]["previous_segment_id"], None)
            self.assertEqual(segments[-1]["next_segment_id"], None)


if __name__ == "__main__":
    unittest.main()
