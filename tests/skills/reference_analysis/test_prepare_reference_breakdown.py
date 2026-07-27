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


FIXTURE = Path(__file__).with_name("fixtures") / "local-draft-v1.mp4"


def prepare_request(media_sha256: str) -> dict[str, object]:
    return {
        "analysis_version": "1.0.0",
        "mode": "local_draft_v1",
        "selected_reference_video": {
            "reference_id": "local-draft-reference-001",
            "media_path": "inputs/reference.mp4",
            "sha256": media_sha256,
            "source_platform": "local",
            "source_url": "urn:local:synthetic-fixture:local-draft-v1",
            "source_id": "local-draft-v1",
            "published_at": "2026-07-27T00:00:00Z",
            "collected_at": "2026-07-27T00:00:00Z",
            "category": "synthetic test video",
            "reference_brand": "Synthetic Reference Brand",
            "reference_product": "Synthetic Reference Product",
            "reference_people": [],
            "provenance": {
                "fixture_id": "local-draft-v1",
                "fixture_kind": "VERSIONED_SYNTHETIC_MEDIA",
            },
        },
    }


class PrepareReferenceBreakdownTests(unittest.TestCase):
    def test_cli_prepares_local_draft_package_with_real_keyframes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            media = workspace / "inputs" / "reference.mp4"
            media.parent.mkdir()
            shutil.copyfile(FIXTURE, media)
            request_path = workspace / "prepare.json"
            request_path.write_text(
                json.dumps(prepare_request(hashlib.sha256(media.read_bytes()).hexdigest())),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "prepare-reference-breakdown",
                    "--input", str(request_path),
                    "--workspace", str(workspace),
                ])

            self.assertEqual(code, 0, stdout.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["output_root"], "reference_breakdown_draft")
            root = workspace / "reference_breakdown_draft"
            manifest = json.loads((root / "draft_manifest.json").read_text(encoding="utf-8"))
            self.assertIs(manifest["draft"], True)
            self.assertEqual(manifest["draft_version"], "local_draft_v1")
            self.assertEqual(manifest["provider_calls"], 0)
            self.assertIs(manifest["external_upload"], False)
            keyframes = manifest["keyframes"]
            self.assertEqual([item["timestamp_ms"] for item in keyframes], [0, 2000, 3999])
            for item in keyframes:
                payload = (workspace / item["path"]).read_bytes()
                self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(hashlib.sha256(payload).hexdigest(), item["sha256"])


if __name__ == "__main__":
    unittest.main()
