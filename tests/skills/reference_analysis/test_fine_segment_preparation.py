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

    def test_every_fine_segment_has_real_start_representative_and_end_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = prepare_reference_breakdown(ten_segment_request(workspace), workspace=workspace)
            root = workspace / result.output_root

            segments = json.loads((root / "fine_segments.json").read_text(encoding="utf-8"))
            frames = json.loads((root / "keyframes" / "index.json").read_text(encoding="utf-8"))
            analyses = json.loads((root / "segment_analysis.json").read_text(encoding="utf-8"))

            for segment in segments:
                owned = [frame for frame in frames if frame["segment_id"] == segment["segment_id"]]
                self.assertEqual(
                    {frame["frame_role"] for frame in owned},
                    {"start", "representative", "end"},
                )
                self.assertTrue(
                    all(segment["start_ms"] <= frame["timestamp_ms"] < segment["end_ms"] for frame in owned)
                )
                self.assertTrue(all(len(frame["sha256"]) == 64 for frame in owned))
                self.assertTrue(all((workspace / frame["asset_path"]).is_file() for frame in owned))
            self.assertEqual(
                {item["segment_id"] for item in analyses},
                {item["segment_id"] for item in segments},
            )
            self.assertTrue(all(len(item["observations"]) == 15 for item in analyses))
            self.assertTrue(
                all(
                    item["observations"]["speech_music_sound_effect"]
                    == {"value": "UNAVAILABLE", "evidence_refs": []}
                    for item in analyses
                )
            )
            self.assertTrue(all(item["analysis_provenance"]["audio_available"] is False for item in analyses))

    def test_preparation_merges_only_adjacent_semantically_matching_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = prepare_reference_breakdown(ten_segment_request(workspace), workspace=workspace)
            request = json.loads(
                (workspace / result.output_root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
            )

            config = request["analysis_configuration"]
            self.assertEqual(len(config["fine_segments"]), 10)
            beats = config["core_beats"]
            self.assertEqual(len(beats), 5)
            self.assertEqual(beats[0]["source_segment_ids"], ["segment-001", "segment-002"])
            self.assertEqual(
                config["bottom_line_formula"]["value"],
                "Problem Hook -> Product Reveal -> Use Demo -> Result Proof -> Natural Close",
            )
            flattened = [segment_id for beat in beats for segment_id in beat["source_segment_ids"]]
            self.assertEqual(flattened, [f"segment-{index:03d}" for index in range(1, 11)])

    def test_fine_mode_runs_with_only_local_detectors_when_optional_inputs_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = ten_segment_request(workspace)
            del request["offline_analysis"]
            del request["segmentation_policy"]

            result = prepare_reference_breakdown(request, workspace=workspace)

            root = workspace / result.output_root
            manifest = json.loads((root / "draft_manifest.json").read_text(encoding="utf-8"))
            segments = json.loads((root / "fine_segments.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(segments), 1)
            self.assertEqual(segments[0]["start_ms"], 0)
            self.assertEqual(segments[-1]["end_ms"], 4000)
            self.assertEqual(manifest["network_calls"], 0)
            self.assertEqual(manifest["provider_calls"], 0)
            self.assertIs(manifest["external_upload"], False)


if __name__ == "__main__":
    unittest.main()
