from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import analyze_storyboard, prepare_reference_breakdown

from tests.skills.reference_analysis.fine_segment_fixture import replication_request
from tests.skills.reference_analysis.test_fine_segment_publication import png_text_chunks


class ReplicationBlueprintPublicationTests(unittest.TestCase):
    def test_hybrid_profile_publishes_complete_traceable_replication_blueprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            prepared = prepare_reference_breakdown(replication_request(workspace), workspace=workspace)
            draft_root = workspace / prepared.output_root
            request = json.loads(
                (draft_root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
            )

            result = analyze_storyboard(request, workspace=workspace)

            root = workspace / result.output_root
            expected = {
                "fine_segments.json",
                "segment_analysis.json",
                "motion_keyframes.json",
                "motion_transitions.json",
                "motion_keyframe_atlas.png",
                "narrative_event_graph.json",
                "reference_storyboard_analysis.json",
                "reference_storyboard_analysis_board.png",
                "scene_blocking_map.json",
                "replication_constraints.json",
                "coverage_report.json",
                "analysis_provenance.json",
                "reference_blueprint.json",
            }
            self.assertTrue(expected.issubset({path.name for path in root.iterdir()}))
            artifact = json.loads((root / "reference_storyboard_analysis.json").read_text(encoding="utf-8"))
            blueprint = json.loads((root / "reference_blueprint.json").read_text(encoding="utf-8"))
            provenance = json.loads((root / "analysis_provenance.json").read_text(encoding="utf-8"))
            frames = artifact["reference_blueprint"]["shared_timeline"]["keyframes"]

            self.assertEqual(artifact["analysis_profile"], "HYBRID_REPLICATION")
            self.assertEqual(blueprint["artifact_semantics"], "ReferenceBlueprint")
            self.assertIsNone(blueprint["formal_contract_identity"])
            self.assertEqual(len(artifact["reference_beats"]), 5)
            self.assertEqual(
                [beat["source_segment_ids"] for beat in artifact["reference_beats"]],
                [event["source_segments"] for event in blueprint["narrative"]["events"]],
            )
            self.assertEqual(
                len(frames),
                len({(frame["segment_id"], frame["timestamp_ms"]) for frame in frames}),
            )
            self.assertTrue(
                all(
                    {"shot_id", "scene_id", "action_roles", "narrative_roles"}.issubset(frame)
                    for frame in frames
                )
            )
            atlas = png_text_chunks((root / "motion_keyframe_atlas.png").read_bytes())
            atlas_layout = json.loads(atlas["avp-layout"])
            self.assertEqual(atlas_layout["board_role"], "motion_keyframe_atlas")
            self.assertEqual(len(atlas_layout["action_groups"]), 3)
            self.assertEqual(provenance["network_calls"], 0)
            self.assertEqual(provenance["provider_calls"], 0)
            self.assertIs(provenance["external_upload"], False)
            self.assertEqual(provenance["blueprint_trace"]["analysis_profile"], "HYBRID_REPLICATION")
            self.assertEqual(len(provenance["blueprint_trace"]["action_ids"]), 3)
            self.assertEqual(len(provenance["blueprint_trace"]["event_ids"]), 5)


if __name__ == "__main__":
    unittest.main()
