from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import analyze_reference, compare_result
from ai_video_platform.skills.reference_analysis.cli import main


def selected_reference(reference_id: str = "ref-1") -> dict[str, object]:
    return {
        "reference_id": reference_id,
        "source_uri": f"task://selected/{reference_id}",
        "sha256": hashlib.sha256(reference_id.encode()).hexdigest(),
        "usage": "analysis",
        "provenance": {"selected_by": "user", "selection_id": "selection-1"},
        "segments": [
            {"start": 0.0, "end": 1.0, "shot_type": "close_up", "emotion": "surprise", "visual_motifs": ["product", "hands"], "is_hook": True},
            {"start": 1.0, "end": 3.0, "shot_type": "wide", "emotion": "trust", "visual_motifs": ["room", "product"], "is_cta": True},
        ],
    }


def analyze_request(reference_id: str = "ref-1") -> dict[str, object]:
    return {"analysis_version": "1.0.0", "selected_reference": selected_reference(reference_id)}


class ReferenceAnalysisInterfaceTests(unittest.TestCase):
    def test_analyze_reference_is_deterministic_versioned_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            first = analyze_reference(analyze_request(), workspace=workspace, output_path="reports/analysis.json")
            second = analyze_reference(analyze_request(), workspace=workspace, output_path="reports/analysis.json")
            self.assertEqual(first, second)
            self.assertEqual(first.artifact["schema_version"], "1.0.0")
            self.assertEqual(first.artifact["algorithm_version"], "1.0.0")
            self.assertEqual(first.artifact["metrics"]["segment_count"], 2)
            self.assertEqual(first.artifact["metrics"]["total_duration"], 3.0)
            stored = workspace / "reports" / "analysis.json"
            self.assertEqual(json.loads(stored.read_text(encoding="utf-8")), first.to_dict()["artifact"])
            self.assertFalse(list(workspace.rglob("*.tmp")))

    def test_compare_result_is_deterministic_and_reports_ordered_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            analysis = analyze_reference(analyze_request(), workspace=workspace, output_path="analysis.json")
            produced = selected_reference()
            produced["segments"] = [
                {"start": 0.0, "end": 2.5, "shot_type": "wide", "emotion": "neutral", "visual_motifs": ["room"]},
            ]
            request = {"analysis_version": "1.0.0", "analysis": analysis.artifact, "produced_result": produced}
            first = compare_result(request, workspace=workspace, output_path="comparison.json")
            second = compare_result(request, workspace=workspace, output_path="comparison.json")
            self.assertEqual(first, second)
            self.assertEqual(first.artifact["reference_id"], "ref-1")
            self.assertIn("product", first.artifact["missing_motifs"])
            gap_metrics = {item["metric"] for item in first.artifact["ordered_gaps"]}
            self.assertTrue(any(metric.startswith("shot_distribution.") for metric in gap_metrics))
            self.assertTrue(any(metric.startswith("emotion_distribution.") for metric in gap_metrics))
            severities = [item["severity_rank"] for item in first.artifact["ordered_gaps"]]
            self.assertEqual(severities, sorted(severities, reverse=True))

    def test_cli_analyze_returns_machine_readable_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request_path = workspace / "request.json"
            request_path.write_text(json.dumps(analyze_request()), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["analyze-reference", "--input", str(request_path), "--workspace", str(workspace), "--output", "cli-analysis.json"])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "COMPLETED")
            self.assertTrue((workspace / "cli-analysis.json").is_file())

    def test_reference_analysis_has_no_private_viral_import(self) -> None:
        source_root = Path(__file__).resolve().parents[3] / "src" / "ai_video_platform" / "skills" / "reference_analysis"
        source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.glob("*.py"))
        self.assertNotIn("viral_research_asset_collection", source)


if __name__ == "__main__":
    unittest.main()
