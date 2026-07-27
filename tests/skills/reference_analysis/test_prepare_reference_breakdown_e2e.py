from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis.cli import main
from tests.skills.reference_analysis.test_prepare_reference_breakdown import FIXTURE, prepare_request


OBSERVATION_FIELDS = (
    "scene",
    "shot_scale",
    "camera_motion",
    "character_action",
    "product_action",
    "product_state",
    "emotion",
    "audience_psychology",
    "conversion_function",
    "viral_mechanism",
    "comment_evidence",
    "actual_reference_behavior",
    "reusable_pattern",
    "product_transfer_suggestion",
)


class PrepareReferenceBreakdownE2ETests(unittest.TestCase):
    def test_prepare_output_is_consumed_by_analyze_storyboard_in_the_same_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            media = workspace / "inputs" / "reference.mp4"
            media.parent.mkdir()
            shutil.copyfile(FIXTURE, media)
            prepare_path = workspace / "prepare.json"
            prepare_path.write_text(
                json.dumps(prepare_request(hashlib.sha256(media.read_bytes()).hexdigest())),
                encoding="utf-8",
            )

            prepare_stdout = io.StringIO()
            with redirect_stdout(prepare_stdout):
                prepare_code = main([
                    "prepare-reference-breakdown",
                    "--input", str(prepare_path),
                    "--workspace", str(workspace),
                ])
            self.assertEqual(prepare_code, 0, prepare_stdout.getvalue())

            request_path = workspace / "reference_breakdown_draft" / "analyze_storyboard_request.json"
            analyze_request = json.loads(request_path.read_text(encoding="utf-8"))
            timeline = analyze_request["analysis_configuration"]["timeline"]
            self.assertEqual(timeline[0]["start_ms"], 0)
            self.assertEqual(timeline[-1]["end_ms"], 4000)
            for beat in timeline:
                self.assertEqual(set(OBSERVATION_FIELDS), set(beat).intersection(OBSERVATION_FIELDS))
                for name in OBSERVATION_FIELDS:
                    self.assertTrue(beat[name]["value"].startswith("DRAFT:"), (name, beat[name]))
                self.assertEqual(beat["comment_evidence"]["evidence_refs"], [])

            analyze_stdout = io.StringIO()
            with redirect_stdout(analyze_stdout):
                analyze_code = main([
                    "analyze-storyboard",
                    "--input", str(request_path),
                    "--workspace", str(workspace),
                ])
            self.assertEqual(analyze_code, 0, analyze_stdout.getvalue())
            result = json.loads(analyze_stdout.getvalue())
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["output_root"], "reference_analysis")
            artifact = json.loads(
                (workspace / "reference_analysis" / "reference_storyboard_analysis.json").read_text(encoding="utf-8")
            )
            self.assertIs(artifact["artifact_role_restrictions"]["provider_execution_input"], False)
            self.assertIs(artifact["artifact_role_restrictions"]["first_frame_eligible"], False)
            self.assertIs(artifact["artifact_role_restrictions"]["production_storyboard"], False)


if __name__ == "__main__":
    unittest.main()
