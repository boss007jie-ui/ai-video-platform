from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import (
    ErrorCode,
    SkillError,
    analyze_storyboard,
    build_analysis_brief_from_choices,
    prepare_reference_breakdown,
)
from ai_video_platform.skills.reference_analysis.analysis_brief import (
    derive_analysis_profile,
    requires_replication_package,
)

from tests.skills.reference_analysis.fine_segment_fixture import (
    complete_visual_observation,
    replication_request,
    ten_segment_request,
)
from tests.skills.reference_analysis.test_storyboard_analysis import materialize_fixture


class AnalysisBriefAndVisualGateTests(unittest.TestCase):
    def test_skill_requires_replication_target_and_inference_policy_as_separate_questions(self) -> None:
        skill = (
            Path(__file__).parents[3]
            / "src"
            / "ai_video_platform"
            / "skills"
            / "reference_analysis"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

        target_question = "Question 1 - replication target"
        inference_question = "Question 2 - inference policy"
        self.assertIn(target_question, skill)
        self.assertIn(inference_question, skill)
        self.assertLess(skill.index(target_question), skill.index(inference_question))
        for label in (
            "1:1 motion replication",
            "story/narrative replication",
            "motion + story replication",
            "quick structural overview",
            "observed facts only",
            "labeled hypotheses allowed",
            "Never combine the two questions into precomposed bundles",
        ):
            self.assertIn(label, skill)

    def test_two_user_choices_map_to_distinct_replication_targets(self) -> None:
        cases = {
            "MOTION_1_TO_1": (
                ["MOTION", "SCENE_BLOCKING"],
                "MOTION_REPLICATION",
                "DETAILED",
            ),
            "NARRATIVE_1_TO_1": (
                ["NARRATIVE", "EDITING_RHYTHM", "AUDIO_VISUAL"],
                "NARRATIVE_REPLICATION",
                "DETAILED",
            ),
            "HYBRID_1_TO_1": (
                [
                    "MOTION",
                    "NARRATIVE",
                    "PRODUCT_PROOF",
                    "SCENE_BLOCKING",
                    "EDITING_RHYTHM",
                    "AUDIO_VISUAL",
                ],
                "HYBRID_REPLICATION",
                "DETAILED",
            ),
            "QUICK_OVERVIEW": (
                ["EDITING_RHYTHM", "AUDIO_VISUAL"],
                "NARRATIVE_REPLICATION",
                "OVERVIEW",
            ),
        }
        for target, (focus, profile, depth) in cases.items():
            with self.subTest(target=target):
                brief = build_analysis_brief_from_choices(target, "FACTS_ONLY")
                self.assertEqual(brief["focus"], focus)
                self.assertEqual(brief["depth"], depth)
                self.assertEqual(brief["hypothesis_policy"], "OBSERVED_ONLY")
                self.assertEqual(derive_analysis_profile(brief), profile)
                self.assertEqual(requires_replication_package(brief), target != "QUICK_OVERVIEW")

        hypothesis_brief = build_analysis_brief_from_choices(
            "HYBRID_1_TO_1",
            "LABELED_HYPOTHESES",
        )
        self.assertEqual(hypothesis_brief["hypothesis_policy"], "LABEL_UNVERIFIED")

    def test_fine_analysis_requires_an_explicit_analysis_brief(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = ten_segment_request(workspace)
            request.pop("analysis_brief", None)

            with self.assertRaises(SkillError) as captured:
                prepare_reference_breakdown(request, workspace=workspace)

            self.assertEqual(captured.exception.code, ErrorCode.VALIDATION_FAILED)
            self.assertIn("request.analysis_brief", captured.exception.field_paths)
            self.assertFalse((workspace / "reference_breakdown_draft").exists())

    def test_publication_requires_completed_visual_observation_for_every_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            prepared = prepare_reference_breakdown(replication_request(workspace), workspace=workspace)
            request = json.loads(
                (workspace / prepared.output_root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
            )

            visual_observation = request["analysis_configuration"]["visual_observation"]
            self.assertEqual(visual_observation["status"], "REQUIRED")
            self.assertTrue(visual_observation["frames"])
            self.assertTrue(all(frame["observed"] is False for frame in visual_observation["frames"]))
            self.assertTrue(all(frame["visual_facts"] == [] for frame in visual_observation["frames"]))

            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(request, workspace=workspace)

            self.assertEqual(captured.exception.code, ErrorCode.VISUAL_OBSERVATION_REQUIRED)
            self.assertFalse((workspace / "reference_analysis").exists())

    def test_publication_accepts_a_digest_bound_all_frame_visual_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            prepared = prepare_reference_breakdown(replication_request(workspace), workspace=workspace)
            request = json.loads(
                (workspace / prepared.output_root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
            )
            complete_visual_observation(request, observer_id="codex-vision-test")

            result = analyze_storyboard(request, workspace=workspace)

            self.assertEqual(result.status, "COMPLETED")
            self.assertEqual(result.artifact["visual_observation"]["status"], "COMPLETED")
            self.assertEqual(result.artifact["visual_observation"]["observer_id"], "codex-vision-test")

    def test_boolean_attestation_without_per_frame_visual_facts_cannot_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            prepared = prepare_reference_breakdown(replication_request(workspace), workspace=workspace)
            request = json.loads(
                (workspace / prepared.output_root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
            )
            receipt = request["analysis_configuration"]["visual_observation"]
            receipt["status"] = "COMPLETED"
            receipt["observer_id"] = "unverified-agent"
            receipt["method"] = "agent_image_understanding"
            for frame in receipt["frames"]:
                frame["observed"] = True

            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(request, workspace=workspace)

            self.assertEqual(captured.exception.code, ErrorCode.VISUAL_OBSERVATION_REQUIRED)

    def test_unavailable_or_draft_text_is_not_a_visual_fact(self) -> None:
        for description in (
            "UNAVAILABLE",
            "DRAFT: image was not opened",
            "The image was inspected successfully.",
        ):
            with self.subTest(description=description):
                with tempfile.TemporaryDirectory() as directory:
                    workspace = Path(directory)
                    prepared = prepare_reference_breakdown(replication_request(workspace), workspace=workspace)
                    request = json.loads(
                        (workspace / prepared.output_root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
                    )
                    complete_visual_observation(request)
                    request["analysis_configuration"]["visual_observation"]["frames"][0]["visual_facts"] = [
                        {"category": "FRAME_QUALITY", "description": description}
                    ]

                    with self.assertRaises(SkillError) as captured:
                        analyze_storyboard(request, workspace=workspace)

                    self.assertEqual(captured.exception.code, ErrorCode.VISUAL_OBSERVATION_REQUIRED)

    def test_draft_unavailable_placeholder_cannot_survive_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize_fixture(workspace)
            request["analysis_configuration"]["timeline"][0]["scene"] = {
                "value": "DRAFT: UNAVAILABLE; image was not reviewed.",
                "evidence_refs": [],
            }

            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(request, workspace=workspace)

            self.assertEqual(captured.exception.code, ErrorCode.ANALYSIS_INCOMPLETE)

    def test_draft_marker_inside_stage_title_cannot_survive_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize_fixture(workspace)
            request["analysis_configuration"]["timeline"][0]["stage_title"] = (
                "Reviewed DRAFT: placeholder"
            )

            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(request, workspace=workspace)

            self.assertEqual(captured.exception.code, ErrorCode.ANALYSIS_INCOMPLETE)

    def test_detailed_motion_focus_requires_complete_profile_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize_fixture(workspace)
            request["analysis_brief"] = {
                "objective": "REPLICATION_REFERENCE",
                "focus": ["MOTION", "SCENE_BLOCKING"],
                "depth": "DETAILED",
                "hypothesis_policy": "LABEL_UNVERIFIED",
            }

            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(request, workspace=workspace)

            self.assertEqual(captured.exception.code, ErrorCode.ANALYSIS_INCOMPLETE)

    def test_hybrid_analysis_without_replication_evidence_is_incomplete_and_cannot_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = ten_segment_request(workspace)
            request["analysis_brief"] = {
                "objective": "REPLICATION_REFERENCE",
                "focus": ["MOTION", "NARRATIVE", "SCENE_BLOCKING"],
                "depth": "DETAILED",
                "hypothesis_policy": "LABEL_UNVERIFIED",
            }
            request["analysis_profile"] = "HYBRID_REPLICATION"
            prepared = prepare_reference_breakdown(request, workspace=workspace)
            root = workspace / prepared.output_root

            motion = json.loads((root / "motion_keyframes.json").read_text(encoding="utf-8"))
            narrative = json.loads((root / "narrative_event_graph.json").read_text(encoding="utf-8"))
            scene = json.loads((root / "scene_blocking_map.json").read_text(encoding="utf-8"))
            coverage = json.loads((root / "coverage_report.json").read_text(encoding="utf-8"))
            self.assertEqual(motion["status"], "INCOMPLETE")
            self.assertEqual(narrative["status"], "INCOMPLETE")
            self.assertEqual(scene["status"], "INCOMPLETE")
            self.assertEqual(coverage["status"], "INCOMPLETE")

            publication_request = json.loads(
                (root / "analyze_storyboard_request.json").read_text(encoding="utf-8")
            )
            complete_visual_observation(publication_request)
            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(publication_request, workspace=workspace)

            self.assertEqual(captured.exception.code, ErrorCode.ANALYSIS_INCOMPLETE)
            self.assertFalse((workspace / "reference_analysis").exists())


if __name__ == "__main__":
    unittest.main()
