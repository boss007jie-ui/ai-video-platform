from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import ErrorCode, SkillError, analyze_reference, compare_result
from tests.skills.reference_analysis.test_reference_analysis_interface import analyze_request, selected_reference


class ReferenceAnalysisFailureTests(unittest.TestCase):
    def test_rejects_discovery_download_provider_and_bad_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            for forbidden in ("query", "search_budget", "provider", "download"):
                request = {**analyze_request(), forbidden: "not-allowed"}
                with self.assertRaises(SkillError) as caught:
                    analyze_reference(request, workspace=workspace, output_path=f"{forbidden}.json")
                self.assertEqual(caught.exception.code, ErrorCode.SCOPE_FORBIDDEN)
            bad = analyze_request()
            bad["selected_reference"] = {**selected_reference(), "segments": [{"start": 2.0, "end": 1.0}]}
            with self.assertRaises(SkillError) as caught:
                analyze_reference(bad, workspace=workspace, output_path="bad.json")
            self.assertEqual(caught.exception.code, ErrorCode.VALIDATION_FAILED)

    def test_path_escape_collision_and_cancellation_fail_without_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            for output in ("../escape.json", str(workspace / "absolute.json")):
                with self.assertRaises(SkillError) as caught:
                    analyze_reference(analyze_request(), workspace=workspace, output_path=output)
                self.assertEqual(caught.exception.code, ErrorCode.PATH_FORBIDDEN)
            with self.assertRaises(SkillError) as caught:
                analyze_reference(analyze_request(), workspace=workspace, output_path="cancelled.json", cancelled=lambda: True)
            self.assertEqual(caught.exception.code, ErrorCode.CANCELLED)
            self.assertFalse((workspace / "cancelled.json").exists())
            analyze_reference(analyze_request(), workspace=workspace, output_path="collision.json")
            with self.assertRaises(SkillError) as caught:
                analyze_reference(analyze_request("ref-2"), workspace=workspace, output_path="collision.json")
            self.assertEqual(caught.exception.code, ErrorCode.OUTPUT_CONFLICT)
            self.assertFalse(list(workspace.rglob("*.tmp")))

    def test_symlink_output_is_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            outside = workspace.parent / f"{workspace.name}-outside.json"
            link = workspace / "linked.json"
            try:
                os.symlink(outside, link)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            with self.assertRaises(SkillError) as caught:
                analyze_reference(analyze_request(), workspace=workspace, output_path="linked.json")
            self.assertEqual(caught.exception.code, ErrorCode.PATH_FORBIDDEN)
            self.assertFalse(outside.exists())

    def test_version_and_reference_mismatch_are_stable_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            unsupported = {**analyze_request(), "analysis_version": "2.0.0"}
            with self.assertRaises(SkillError) as caught:
                analyze_reference(unsupported, workspace=workspace, output_path="unsupported.json")
            self.assertEqual(caught.exception.code, ErrorCode.VERSION_UNSUPPORTED)
            analysis = analyze_reference(analyze_request(), workspace=workspace, output_path="analysis.json")
            produced = selected_reference("ref-2")
            with self.assertRaises(SkillError) as caught:
                compare_result(
                    {"analysis_version": "1.0.0", "analysis": analysis.artifact, "produced_result": produced},
                    workspace=workspace, output_path="mismatch.json",
                )
            self.assertEqual(caught.exception.code, ErrorCode.REFERENCE_MISMATCH)
            error = SkillError(ErrorCode.VALIDATION_FAILED, "Bearer synthetic-secret", details={"message": "token synthetic-token"})
            self.assertNotIn("synthetic-secret", error.to_dict()["message"])
            self.assertNotIn("synthetic-token", error.to_dict()["details"]["message"])


if __name__ == "__main__":
    unittest.main()
