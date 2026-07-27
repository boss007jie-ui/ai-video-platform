from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import analyze_storyboard, prepare_reference_breakdown

from tests.skills.reference_analysis.fine_segment_fixture import ten_segment_request


def prepare_request(workspace: Path) -> dict[str, object]:
    result = prepare_reference_breakdown(ten_segment_request(workspace), workspace=workspace)
    return json.loads(
        (workspace / result.output_root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
    )


class FineSegmentPublicationTests(unittest.TestCase):
    def test_analyze_storyboard_publishes_fine_artifacts_and_traceable_core_beats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = analyze_storyboard(prepare_request(workspace), workspace=workspace)
            root = workspace / result.output_root

            expected = {
                "fine_segments.json",
                "segment_analysis.json",
                "reference_storyboard_analysis.json",
                "reference_storyboard_analysis.md",
                "reference_storyboard_analysis_board.png",
                "analysis_provenance.json",
            }
            self.assertTrue(expected.issubset({path.name for path in root.iterdir()}))
            artifact = json.loads((root / "reference_storyboard_analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(len(artifact["fine_segments"]), 10)
            self.assertEqual(len(artifact["reference_beats"]), 5)
            self.assertEqual(
                artifact["reference_beats"][0]["source_segment_ids"],
                ["segment-001", "segment-002"],
            )
            provenance = json.loads((root / "analysis_provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["network_calls"], 0)
            self.assertEqual(provenance["provider_calls"], 0)
            self.assertIs(provenance["external_upload"], False)


if __name__ == "__main__":
    unittest.main()
