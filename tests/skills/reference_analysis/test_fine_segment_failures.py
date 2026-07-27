from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import SkillError, analyze_storyboard

from tests.skills.reference_analysis.test_fine_segment_publication import prepare_request


class FineSegmentFailureTests(unittest.TestCase):
    def test_timing_evidence_and_merge_corruption_fail_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            original = prepare_request(workspace)

            def gap(request: dict[str, object]) -> None:
                request["analysis_configuration"]["fine_segments"][1]["start_ms"] += 1  # type: ignore[index]

            def overlap(request: dict[str, object]) -> None:
                request["analysis_configuration"]["fine_segments"][1]["start_ms"] -= 1  # type: ignore[index]

            def bad_link(request: dict[str, object]) -> None:
                request["analysis_configuration"]["fine_segments"][0]["next_segment_id"] = "segment-999"  # type: ignore[index]

            def frame_outside_segment(request: dict[str, object]) -> None:
                request["analysis_configuration"]["keyframes"][0]["timestamp_ms"] = 500  # type: ignore[index]

            def tampered_frame(request: dict[str, object]) -> None:
                request["analysis_configuration"]["keyframes"][0]["sha256"] = "0" * 64  # type: ignore[index]

            def unknown_evidence(request: dict[str, object]) -> None:
                request["analysis_configuration"]["segment_analysis"][0]["observations"]["scene"]["evidence_refs"] = ["frame:unknown"]  # type: ignore[index]

            def missing_analysis(request: dict[str, object]) -> None:
                request["analysis_configuration"]["segment_analysis"].pop()  # type: ignore[index]

            def non_adjacent_merge(request: dict[str, object]) -> None:
                request["analysis_configuration"]["core_beats"][0]["source_segment_ids"] = ["segment-001", "segment-003"]  # type: ignore[index]

            def incomplete_partition(request: dict[str, object]) -> None:
                request["analysis_configuration"]["core_beats"].pop()  # type: ignore[index]

            def representative_outside_beat(request: dict[str, object]) -> None:
                request["analysis_configuration"]["core_beats"][0]["representative_frame_id"] = "segment-003-representative"  # type: ignore[index]

            corruptions = {
                "gap": gap,
                "overlap": overlap,
                "bad_link": bad_link,
                "frame_outside_segment": frame_outside_segment,
                "tampered_frame": tampered_frame,
                "unknown_evidence": unknown_evidence,
                "missing_analysis": missing_analysis,
                "non_adjacent_merge": non_adjacent_merge,
                "incomplete_partition": incomplete_partition,
                "representative_outside_beat": representative_outside_beat,
            }
            for name, corrupt in corruptions.items():
                with self.subTest(name=name):
                    request = copy.deepcopy(original)
                    corrupt(request)
                    with self.assertRaises(SkillError):
                        analyze_storyboard(request, workspace=workspace)
                    self.assertFalse((workspace / "reference_analysis").exists())

    def test_partial_fine_package_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = prepare_request(workspace)
            del request["analysis_configuration"]["segment_analysis"]  # type: ignore[index]

            with self.assertRaises(SkillError):
                analyze_storyboard(request, workspace=workspace)

            self.assertFalse((workspace / "reference_analysis").exists())


if __name__ == "__main__":
    unittest.main()
