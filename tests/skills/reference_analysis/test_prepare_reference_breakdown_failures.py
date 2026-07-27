from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from ai_video_platform.skills.reference_analysis import (
    ErrorCode,
    SkillError,
    prepare_reference_breakdown,
)
from tests.skills.reference_analysis.test_prepare_reference_breakdown import FIXTURE, prepare_request


def materialize(workspace: Path) -> dict[str, object]:
    media = workspace / "inputs" / "reference.mp4"
    media.parent.mkdir()
    shutil.copyfile(FIXTURE, media)
    return prepare_request(hashlib.sha256(media.read_bytes()).hexdigest())


class PrepareReferenceBreakdownFailureTests(unittest.TestCase):
    def test_non_local_modes_cloud_provider_upload_and_bad_hash_are_rejected(self) -> None:
        mutations = (
            ("mode", "cloud_video_llm", ErrorCode.SCOPE_FORBIDDEN),
            ("cloud_video_llm", {"enabled": True}, ErrorCode.SCOPE_FORBIDDEN),
            ("upload", {"enabled": True}, ErrorCode.SCOPE_FORBIDDEN),
            ("provider", "synthetic-provider", ErrorCode.SCOPE_FORBIDDEN),
        )
        for field, value, expected in mutations:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    workspace = Path(directory)
                    request = materialize(workspace)
                    request[field] = value
                    with self.assertRaises(SkillError) as captured:
                        prepare_reference_breakdown(request, workspace=workspace)
                    self.assertEqual(captured.exception.code, expected)
                    self.assertFalse((workspace / "reference_breakdown_draft").exists())

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize(workspace)
            request["selected_reference_video"]["sha256"] = "0" * 64
            with self.assertRaises(SkillError) as captured:
                prepare_reference_breakdown(request, workspace=workspace)
            self.assertEqual(captured.exception.code, ErrorCode.MEDIA_INVALID)
            self.assertFalse((workspace / "reference_breakdown_draft").exists())

    def test_paths_and_keyframe_limits_fail_closed_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            absolute_request = materialize(workspace)
            absolute_request["selected_reference_video"]["media_path"] = str(
                (workspace / "inputs" / "reference.mp4").resolve()
            )
            with self.assertRaises(SkillError) as captured:
                prepare_reference_breakdown(absolute_request, workspace=workspace)
            self.assertEqual(captured.exception.code, ErrorCode.PATH_FORBIDDEN)

        policies = (
            {"interval_ms": 2000, "max_keyframes": 13},
            {"interval_ms": 1, "max_keyframes": 12},
        )
        for policy in policies:
            with self.subTest(policy=policy):
                with tempfile.TemporaryDirectory() as directory:
                    workspace = Path(directory)
                    request = materialize(workspace)
                    request["video_metadata"] = {
                        "duration_ms": 4000,
                        "width": 64,
                        "height": 96,
                        "aspect_ratio": "2:3",
                        "media_type": "video/mp4",
                        "codec": "h264",
                    }
                    request["policy"] = policy
                    with self.assertRaises(SkillError) as captured:
                        prepare_reference_breakdown(request, workspace=workspace)
                    self.assertEqual(captured.exception.code, ErrorCode.VALIDATION_FAILED)
                    self.assertFalse((workspace / "reference_breakdown_draft").exists())

    def test_caller_supplied_metadata_is_preserved_with_real_local_keyframes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize(workspace)
            metadata = {
                "duration_ms": 4000,
                "width": 64,
                "height": 96,
                "aspect_ratio": "2:3",
                "media_type": "video/mp4",
                "codec": "h264",
            }
            request["video_metadata"] = metadata
            result = prepare_reference_breakdown(request, workspace=workspace)
            self.assertEqual(result.status, "COMPLETED")
            root = workspace / "reference_breakdown_draft"
            manifest = json.loads((root / "draft_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["method_provenance"]["metadata_strategy"], "caller_supplied")
            analyze_request = json.loads((root / "analyze_storyboard_request.json").read_text(encoding="utf-8"))
            self.assertEqual(analyze_request["video_metadata"], metadata)
            for keyframe in analyze_request["analysis_configuration"]["keyframes"]:
                self.assertTrue((workspace / keyframe["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
