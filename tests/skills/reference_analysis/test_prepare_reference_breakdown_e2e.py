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
from tests.skills.reference_analysis.fine_segment_fixture import complete_visual_observation
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
    def test_unreviewed_prepare_placeholders_cannot_be_published_after_receipt_only(self) -> None:
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
                    if name == "product_transfer_suggestion":
                        self.assertEqual(beat[name]["value"], "UNAVAILABLE")
                    elif name in {"audience_psychology", "conversion_function", "viral_mechanism"}:
                        self.assertTrue(beat[name]["value"].startswith("HYPOTHESIS: DRAFT:"), (name, beat[name]))
                    else:
                        self.assertTrue(beat[name]["value"].startswith("DRAFT:"), (name, beat[name]))
                self.assertEqual(beat["comment_evidence"]["evidence_refs"], [])
            complete_visual_observation(analyze_request)
            request_path.write_text(json.dumps(analyze_request), encoding="utf-8")

            analyze_stdout = io.StringIO()
            with redirect_stdout(analyze_stdout):
                analyze_code = main([
                    "analyze-storyboard",
                    "--input", str(request_path),
                    "--workspace", str(workspace),
                ])
            self.assertEqual(analyze_code, 2, analyze_stdout.getvalue())
            result = json.loads(analyze_stdout.getvalue())
            self.assertEqual(result["status"], "ERROR")
            self.assertEqual(result["error"]["code"], "REFERENCE_ANALYSIS_INCOMPLETE")
            self.assertFalse((workspace / "reference_analysis").exists())


if __name__ == "__main__":
    unittest.main()
