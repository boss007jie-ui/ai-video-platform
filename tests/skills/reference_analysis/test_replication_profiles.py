from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import SkillError, analyze_storyboard, prepare_reference_breakdown

from tests.skills.reference_analysis.fine_segment_fixture import replication_request, ten_segment_request


class ReplicationProfileTests(unittest.TestCase):
    def test_motion_and_narrative_profiles_select_different_semantic_frames(self) -> None:
        selected: dict[str, list[dict[str, object]]] = {}
        for profile in ("MOTION_REPLICATION", "NARRATIVE_REPLICATION"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                result = prepare_reference_breakdown(
                    replication_request(workspace, profile=profile),
                    workspace=workspace,
                )
                root = workspace / result.output_root
                segments = json.loads((root / "fine_segments.json").read_text(encoding="utf-8"))
                selected[profile] = json.loads(
                    (root / "keyframes" / "index.json").read_text(encoding="utf-8")
                )
                self.assertTrue(all(segment["shot_id"] and segment["scene_id"] for segment in segments))

        motion_frames = selected["MOTION_REPLICATION"]
        narrative_frames = selected["NARRATIVE_REPLICATION"]
        self.assertTrue(any(frame["action_roles"] for frame in motion_frames))
        self.assertTrue(all(not frame["narrative_roles"] for frame in motion_frames))
        self.assertTrue(any(frame["narrative_roles"] for frame in narrative_frames))
        self.assertTrue(all(not frame["action_roles"] for frame in narrative_frames))
        self.assertNotEqual(
            [frame["timestamp_ms"] for frame in motion_frames],
            [frame["timestamp_ms"] for frame in narrative_frames],
        )

    def test_profile_is_explicitly_carried_into_the_publication_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = ten_segment_request(workspace)
            request["analysis_profile"] = "MOTION_REPLICATION"

            result = prepare_reference_breakdown(request, workspace=workspace)

            root = workspace / result.output_root
            manifest = json.loads((root / "draft_manifest.json").read_text(encoding="utf-8"))
            publication = json.loads(
                (root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["analysis_profile"], "MOTION_REPLICATION")
            self.assertEqual(publication["analysis_profile"], "MOTION_REPLICATION")

    def test_every_profile_completes_the_public_prepare_and_publish_flow(self) -> None:
        for profile in ("MOTION_REPLICATION", "NARRATIVE_REPLICATION", "HYBRID_REPLICATION"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                prepared = prepare_reference_breakdown(
                    replication_request(workspace, profile=profile),
                    workspace=workspace,
                )
                publication_request = json.loads(
                    (workspace / prepared.output_root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
                )

                published = analyze_storyboard(publication_request, workspace=workspace)

                self.assertEqual(published.status, "COMPLETED")
                self.assertEqual(published.artifact["analysis_profile"], profile)

    def test_unknown_profile_fails_before_media_processing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = ten_segment_request(workspace)
            request["analysis_profile"] = "ONE_FRAME_PER_SEGMENT"

            with self.assertRaises(SkillError):
                prepare_reference_breakdown(request, workspace=workspace)


if __name__ == "__main__":
    unittest.main()
