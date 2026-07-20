from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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

            for source_uri in ("legacy://asset/1", "product-library://asset/1", "research-library://asset/1", "Legacy/asset.json"):
                forbidden_uri = analyze_request()
                forbidden_uri["selected_reference"] = {**selected_reference(), "source_uri": source_uri}
                with self.assertRaises(SkillError) as caught:
                    analyze_reference(forbidden_uri, workspace=workspace, output_path="forbidden-uri.json")
                self.assertEqual(caught.exception.code, ErrorCode.SCOPE_FORBIDDEN)

            for provenance in (
                {"selected_by": "user", "origin": "Legacy/asset.json"},
                {"selected_by": "user", "origin_path": "../outside.json"},
                {"selected_by": "user", "note": "product-library://asset/1"},
            ):
                forbidden_value = analyze_request()
                forbidden_value["selected_reference"] = {**selected_reference(), "provenance": provenance}
                with self.assertRaises(SkillError) as caught:
                    analyze_reference(forbidden_value, workspace=workspace, output_path="forbidden-value.json")
                self.assertEqual(caught.exception.code, ErrorCode.SCOPE_FORBIDDEN)

            nested = analyze_request()
            nested["selected_reference"] = {**selected_reference(), "provenance": {"selected_by": "user", "provider": "forbidden"}}
            with self.assertRaises(SkillError) as caught:
                analyze_reference(nested, workspace=workspace, output_path="nested.json")
            self.assertEqual(caught.exception.code, ErrorCode.SCOPE_FORBIDDEN)

            unknown = {**analyze_request(), "unexpected": True}
            with self.assertRaises(SkillError) as caught:
                analyze_reference(unknown, workspace=workspace, output_path="unknown.json")
            self.assertEqual(caught.exception.code, ErrorCode.VALIDATION_FAILED)

    def test_pre_cancelled_request_wins_before_segment_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bad = analyze_request()
            bad["selected_reference"] = {**selected_reference(), "segments": "invalid"}
            with self.assertRaises(SkillError) as caught:
                analyze_reference(bad, workspace=Path(directory), output_path="cancelled.json", cancelled=lambda: True)
            self.assertEqual(caught.exception.code, ErrorCode.CANCELLED)

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

    def test_atomic_publish_never_clobbers_a_racing_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            target = workspace / "race.json"

            def racing_link(source, destination):
                del source
                Path(destination).write_bytes(b"racing-writer")
                raise FileExistsError

            with patch("ai_video_platform.skills.reference_analysis.storage.os.link", side_effect=racing_link):
                with self.assertRaises(SkillError) as caught:
                    analyze_reference(analyze_request(), workspace=workspace, output_path="race.json")
            self.assertEqual(caught.exception.code, ErrorCode.OUTPUT_CONFLICT)
            self.assertEqual(target.read_bytes(), b"racing-writer")
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

            tampered = analysis.to_dict()["artifact"]
            tampered["metrics"]["segment_count"] = 999
            with self.assertRaises(SkillError) as caught:
                compare_result(
                    {"analysis_version": "1.0.0", "analysis": tampered, "produced_result": selected_reference()},
                    workspace=workspace, output_path="tampered.json",
                )
            self.assertEqual(caught.exception.code, ErrorCode.VALIDATION_FAILED)

            wrong_source = selected_reference()
            wrong_source["sha256"] = "0" * 64
            with self.assertRaises(SkillError) as caught:
                compare_result(
                    {"analysis_version": "1.0.0", "analysis": analysis.artifact, "produced_result": wrong_source},
                    workspace=workspace, output_path="wrong-source.json",
                )
            self.assertEqual(caught.exception.code, ErrorCode.REFERENCE_MISMATCH)
            error = SkillError(ErrorCode.VALIDATION_FAILED, "Bearer synthetic-secret", details={"message": "token synthetic-token"})
            self.assertNotIn("synthetic-secret", error.to_dict()["message"])
            self.assertNotIn("synthetic-token", error.to_dict()["details"]["message"])


if __name__ == "__main__":
    unittest.main()
