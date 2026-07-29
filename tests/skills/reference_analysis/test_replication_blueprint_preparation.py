from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import prepare_reference_breakdown

from tests.skills.reference_analysis.fine_segment_fixture import replication_request


class ReplicationBlueprintPreparationTests(unittest.TestCase):
    def test_segment_analysis_keeps_fact_action_subtitle_and_source_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = prepare_reference_breakdown(replication_request(workspace), workspace=workspace)
            root = workspace / result.output_root
            analyses = json.loads((root / "segment_analysis.json").read_text(encoding="utf-8"))

            self.assertTrue(all("facts" in analysis and "motion_evidence" in analysis for analysis in analyses))
            contact_segment = analyses[1]
            self.assertIn(
                "FIRST_CONTACT",
                {
                    state["action_state"]
                    for action in contact_segment["motion_evidence"]
                    for state in action["states"]
                },
            )
            self.assertTrue(contact_segment["facts"])
            self.assertTrue(contact_segment["subtitle_evidence"])
            self.assertEqual(contact_segment["audio_evidence"], [])

    def test_scene_blocking_and_replication_constraints_separate_preserved_and_replaceable_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = prepare_reference_breakdown(replication_request(workspace), workspace=workspace)
            root = workspace / result.output_root

            scene_map = json.loads((root / "scene_blocking_map.json").read_text(encoding="utf-8"))
            constraints = json.loads((root / "replication_constraints.json").read_text(encoding="utf-8"))
            blueprint = json.loads((root / "reference_blueprint.json").read_text(encoding="utf-8"))
            self.assertEqual(len(scene_map["scenes"]), 2)
            first = scene_map["scenes"][0]
            self.assertEqual(first["scene_type"], "bed demonstration")
            self.assertEqual(first["subject_position"], "center")
            self.assertIn("scene_type", first["preservation"]["MUST_PRESERVE"])
            self.assertIn("soft_furnishing_pattern", first["preservation"]["REPLACEABLE"])
            self.assertIn("camera_height", first["preservation"]["CONDITIONALLY_REPLACEABLE"])

            self.assertIn("body_proportions", constraints["person"]["MUST_PRESERVE"])
            self.assertIn("face_identity", constraints["person"]["REPLACEABLE"])
            self.assertIn("brand_identity", constraints["product"]["REPLACEABLE"])
            self.assertTrue(constraints["identity_restrictions"]["reference_identity_must_not_be_copied"])
            self.assertEqual(blueprint["artifact_semantics"], "ReferenceBlueprint")
            self.assertIsNone(blueprint["formal_contract_identity"])
            self.assertEqual(blueprint["analysis_profile"], "HYBRID_REPLICATION")

    def test_narrative_graph_uses_facts_events_causality_and_repeated_proof_loops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = replication_request(workspace, profile="NARRATIVE_REPLICATION")
            result = prepare_reference_breakdown(request, workspace=workspace)
            root = workspace / result.output_root

            graph = json.loads((root / "narrative_event_graph.json").read_text(encoding="utf-8"))
            coverage = json.loads((root / "coverage_report.json").read_text(encoding="utf-8"))
            self.assertEqual(len(graph["facts"]), 10)
            self.assertEqual(len(graph["events"]), 5)
            self.assertEqual(len(graph["causal_edges"]), 4)
            self.assertEqual(
                {node["role"] for node in graph["global_story"]},
                {"SETUP", "INCITING_EVENT", "INFORMATION_CHANGE", "PRODUCT_PROOF", "REACTION", "ESCALATION", "REVEAL", "NATURAL_CLOSE"},
            )
            self.assertEqual(len(graph["repeated_product_proof_loops"]), 2)
            self.assertEqual(
                {loop["repeated_structure_id"] for loop in graph["repeated_product_proof_loops"]},
                {"proof-structure-001"},
            )
            self.assertEqual(coverage["narrative_coverage"]["status"], "PASS")
            self.assertGreater(coverage["narrative_coverage"]["added_frame_count"], 0)
            self.assertEqual(coverage["narrative_coverage"]["unresolved_gaps"], [])

    def test_motion_blueprint_captures_contact_states_transitions_and_coverage_additions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = prepare_reference_breakdown(replication_request(workspace), workspace=workspace)
            root = workspace / result.output_root

            motion = json.loads((root / "motion_keyframes.json").read_text(encoding="utf-8"))
            transitions = json.loads((root / "motion_transitions.json").read_text(encoding="utf-8"))
            coverage = json.loads((root / "coverage_report.json").read_text(encoding="utf-8"))
            keyframes = json.loads((root / "keyframes" / "index.json").read_text(encoding="utf-8"))
            frame_ids = {frame["frame_id"] for frame in keyframes}

            self.assertEqual(motion["analysis_profile"], "HYBRID_REPLICATION")
            self.assertEqual(len(motion["action_chains"]), 3)
            first = motion["action_chains"][0]
            self.assertEqual(
                [state["action_state"] for state in first["states"]],
                [
                    "ACTION_START",
                    "ACTION_ONSET",
                    "PRE_CONTACT",
                    "FIRST_CONTACT",
                    "CONTROL_OR_GRIP",
                    "ACTION_APEX",
                    "ACTION_END",
                    "FINAL_HOLD",
                ],
            )
            self.assertIn("FIRST_CONTACT", {state["contact_state"] for state in first["states"]})
            self.assertTrue(all(state["frame_id"] in frame_ids for state in first["states"]))
            self.assertGreater(first["action_duration_ms"], 0)
            self.assertGreaterEqual(len(first["source_segments"]), 2)

            required_transition_fields = {
                "from_frame_id",
                "to_frame_id",
                "start_ms",
                "end_ms",
                "duration_ms",
                "actor",
                "body_part",
                "motion_path",
                "direction",
                "speed_profile",
                "contact_state_before",
                "contact_state_during",
                "contact_state_after",
                "product_motion",
                "camera_motion",
                "continuity_notes",
            }
            self.assertTrue(transitions["transitions"])
            self.assertTrue(
                all(required_transition_fields.issubset(transition) for transition in transitions["transitions"])
            )
            self.assertEqual(coverage["motion_coverage"]["status"], "PASS")
            self.assertEqual(coverage["motion_coverage"]["iterations"], 1)
            self.assertGreater(coverage["motion_coverage"]["added_frame_count"], 0)
            self.assertEqual(coverage["motion_coverage"]["unresolved_gaps"], [])


if __name__ == "__main__":
    unittest.main()
