from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import ErrorCode, SkillError, analyze_storyboard
from tests.skills.reference_analysis.test_storyboard_analysis import materialize_fixture


class StoryboardAnalysisFailureTests(unittest.TestCase):
    def test_non_unavailable_observation_requires_traceable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize_fixture(workspace)
            request["analysis_configuration"]["timeline"][0]["scene"]["evidence_refs"] = []
            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(request, workspace=workspace)
            self.assertEqual(captured.exception.code, ErrorCode.EVIDENCE_MISSING)
            self.assertIn("analysis_configuration.timeline[0].scene.evidence_refs", captured.exception.field_paths)
            self.assertFalse((workspace / "reference_analysis").exists())

    def test_keyframes_must_exist_match_hash_and_bind_inside_exact_interval(self) -> None:
        mutations = (
            lambda request: request["analysis_configuration"]["keyframes"][0].update({"sha256": "0" * 64}),
            lambda request: request["analysis_configuration"]["keyframes"][0].update({"timestamp_ms": 1700}),
            lambda request: request["analysis_configuration"]["timeline"][0].update({"keyframe_ids": ["kf-missing"]}),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                with tempfile.TemporaryDirectory() as directory:
                    workspace = Path(directory)
                    request = materialize_fixture(workspace)
                    mutate(request)
                    with self.assertRaises(SkillError) as captured:
                        analyze_storyboard(request, workspace=workspace)
                    self.assertIn(captured.exception.code, {ErrorCode.EVIDENCE_MISSING, ErrorCode.MEDIA_INVALID})
                    self.assertFalse((workspace / "reference_analysis").exists())

    def test_unknown_comment_evidence_is_rejected_but_unavailable_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize_fixture(workspace)
            request["analysis_configuration"]["timeline"][0]["comment_evidence"] = {
                "value": "A missing comment claims this",
                "evidence_refs": ["comment:missing"],
            }
            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(request, workspace=workspace)
            self.assertEqual(captured.exception.code, ErrorCode.EVIDENCE_MISSING)

    def test_absent_comments_cannot_be_replaced_with_visual_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize_fixture(workspace, include_comments=False)
            request["analysis_configuration"]["timeline"][0]["comment_evidence"] = {
                "value": "A visual frame cannot establish audience comment evidence",
                "evidence_refs": ["keyframe:kf-001"],
            }
            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(request, workspace=workspace)
            self.assertEqual(captured.exception.code, ErrorCode.EVIDENCE_MISSING)
            self.assertFalse((workspace / "reference_analysis").exists())

    def test_reference_identity_cannot_be_copied_into_product_adaptation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize_fixture(workspace)
            request["analysis_configuration"]["timeline"][0]["product_transfer_suggestion"]["value"] = (
                "Make the current product look exactly like ExampleCo Example Organizer"
            )
            with self.assertRaises(SkillError) as captured:
                analyze_storyboard(request, workspace=workspace)
            self.assertEqual(captured.exception.code, ErrorCode.ARTIFACT_ROLE_FORBIDDEN)
            self.assertFalse((workspace / "reference_analysis").exists())

    def test_production_artifact_or_execution_roles_are_rejected(self) -> None:
        forbidden_keys = ("production_storyboard_plan", "provider_request", "first_frame_mapping")
        for key in forbidden_keys:
            with self.subTest(key=key):
                with tempfile.TemporaryDirectory() as directory:
                    workspace = Path(directory)
                    request = materialize_fixture(workspace)
                    request["analysis_configuration"][key] = {"enabled": True}
                    with self.assertRaises(SkillError) as captured:
                        analyze_storyboard(request, workspace=workspace)
                    self.assertEqual(captured.exception.code, ErrorCode.ARTIFACT_ROLE_FORBIDDEN)
                    self.assertFalse((workspace / "reference_analysis").exists())


if __name__ == "__main__":
    unittest.main()
