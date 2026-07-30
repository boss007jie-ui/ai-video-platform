from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import ErrorCode, SkillError, analyze_storyboard, prepare_reference_breakdown

from tests.skills.reference_analysis.fine_segment_fixture import complete_visual_observation, replication_request


class ReplicationBlueprintFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._temporary_directory.name)
        prepared = prepare_reference_breakdown(replication_request(cls.workspace), workspace=cls.workspace)
        cls.request = json.loads(
            (cls.workspace / prepared.output_root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
        )
        complete_visual_observation(cls.request)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary_directory.cleanup()

    def assert_rejected(self, request: dict[str, object], code: ErrorCode) -> None:
        with self.assertRaises(SkillError) as captured:
            analyze_storyboard(request, workspace=self.workspace)
        self.assertEqual(captured.exception.code, code)

    def test_rejects_profile_mismatch(self) -> None:
        request = copy.deepcopy(self.request)
        request["analysis_brief"]["focus"] = ["MOTION", "SCENE_BLOCKING"]
        request["analysis_profile"] = "MOTION_REPLICATION"

        self.assert_rejected(request, ErrorCode.REFERENCE_MISMATCH)

    def test_rejects_semantic_frame_without_a_semantic_role(self) -> None:
        request = copy.deepcopy(self.request)
        frames = request["analysis_configuration"]["keyframes"]  # type: ignore[index]
        semantic = next(frame for frame in frames if frame["frame_role"] == "semantic")
        semantic["action_roles"] = []
        semantic["narrative_roles"] = []

        self.assert_rejected(request, ErrorCode.EVIDENCE_MISSING)

    def test_rejects_duplicate_segment_timestamp_storage(self) -> None:
        request = copy.deepcopy(self.request)
        frames = request["analysis_configuration"]["keyframes"]  # type: ignore[index]
        duplicate = copy.deepcopy(frames[0])
        duplicate["keyframe_id"] = "duplicated-storage-record"
        frames.append(duplicate)

        self.assert_rejected(request, ErrorCode.VALIDATION_FAILED)

    def test_rejects_motion_transition_using_an_unknown_frame(self) -> None:
        request = copy.deepcopy(self.request)
        config = request["analysis_configuration"]  # type: ignore[assignment]
        config["motion_keyframes"]["transitions"][0]["to_frame_id"] = "unknown-frame"  # type: ignore[index]
        config["motion_transitions"]["transitions"][0]["to_frame_id"] = "unknown-frame"  # type: ignore[index]

        self.assert_rejected(request, ErrorCode.EVIDENCE_MISSING)

    def test_rejects_narrative_event_using_cross_segment_evidence(self) -> None:
        request = copy.deepcopy(self.request)
        event = request["analysis_configuration"]["narrative_event_graph"]["events"][0]  # type: ignore[index]
        event["source_segments"] = ["segment-010"]

        self.assert_rejected(request, ErrorCode.REFERENCE_MISMATCH)

    def test_rejects_montage_or_continuity_relation_that_disagrees_with_source_shots(self) -> None:
        request = copy.deepcopy(self.request)
        transition = request["analysis_configuration"]["narrative_event_graph"]["event_transitions"][0]  # type: ignore[index]
        transition["relation"] = "MONTAGE_CUT"

        self.assert_rejected(request, ErrorCode.REFERENCE_MISMATCH)

    def test_rejects_invalid_coverage_added_frame(self) -> None:
        request = copy.deepcopy(self.request)
        motion_coverage = request["analysis_configuration"]["coverage_report"]["motion_coverage"]  # type: ignore[index]
        motion_coverage["added_frame_ids"] = ["unknown-frame"]
        motion_coverage["added_frame_count"] = 1

        self.assert_rejected(request, ErrorCode.EVIDENCE_MISSING)


if __name__ == "__main__":
    unittest.main()
