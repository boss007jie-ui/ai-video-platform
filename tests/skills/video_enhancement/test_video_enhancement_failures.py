from __future__ import annotations

from pathlib import Path
import hashlib
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_enhancement import EnhancementError, EnhancementErrorCode, VideoEnhancementInterface
from ai_video_platform.skills.video_enhancement.preflight import fake_workflow_profile
from tests.skills.video_enhancement.test_video_enhancement_interface import NOW, SYNTHETIC_MP4, digest, enhancement_request


class VideoEnhancementFailureTests(unittest.TestCase):
    def test_transformed_resolution_must_fit_workflow_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = enhancement_request(media)
            request["operations"][0]["factor"] = 4

            with self.assertRaises(EnhancementError) as captured:
                VideoEnhancementInterface().inspect_enhancement_request(request, now=NOW)

        self.assertEqual(captured.exception.code, EnhancementErrorCode.WORKFLOW_PROFILE_INVALID)

    def test_rights_gate_rejects_unknown_internal_and_third_party_before_adapter(self) -> None:
        cases = (
            ("basis", "UNKNOWN"),
            ("lifecycle", "internal_analysis_only"),
            ("source_class", "third_party_reference"),
            ("fixture_provenance", "research_library_tiktok"),
        )
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            for field, value in cases:
                request = enhancement_request(media)
                request["input"]["rights"][field] = value
                with self.subTest(field=field), self.assertRaises(EnhancementError) as captured:
                    VideoEnhancementInterface().inspect_enhancement_request(request, now=NOW)
                self.assertEqual(captured.exception.code, EnhancementErrorCode.RIGHTS_REJECTED)

    def test_three_research_tiktok_assets_are_permanently_excluded_by_name(self) -> None:
        names = (
            "7665115424106892566.mp4",
            "7663913413235559698.mp4",
            "7655273792406637855.mp4",
        )
        with tempfile.TemporaryDirectory() as directory:
            for name in names:
                media = Path(directory) / name
                media.write_bytes(SYNTHETIC_MP4)
                with self.subTest(name=name), self.assertRaises(EnhancementError) as captured:
                    VideoEnhancementInterface().inspect_enhancement_request(enhancement_request(media), now=NOW)
                self.assertEqual(captured.exception.code, EnhancementErrorCode.RIGHTS_REJECTED)

    def test_local_bytes_extension_size_and_digest_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = []
            wrong_extension = root / "fixture.txt"
            wrong_extension.write_bytes(SYNTHETIC_MP4)
            cases.append((enhancement_request(wrong_extension), EnhancementErrorCode.INPUT_FILE_INVALID))
            wrong_magic = root / "wrong.mp4"
            wrong_magic.write_bytes(b"not-an-mp4")
            wrong_magic_request = enhancement_request(wrong_magic)
            wrong_magic_request["input"]["size_bytes"] = len(b"not-an-mp4")
            wrong_magic_request["input"]["sha256"] = "sha256:" + hashlib.sha256(b"not-an-mp4").hexdigest()
            cases.append((wrong_magic_request, EnhancementErrorCode.INPUT_FILE_INVALID))
            wrong_digest = root / "digest.mp4"
            wrong_digest.write_bytes(SYNTHETIC_MP4)
            wrong_digest_request = enhancement_request(wrong_digest)
            wrong_digest_request["input"]["sha256"] = "sha256:" + "0" * 64
            cases.append((wrong_digest_request, EnhancementErrorCode.INPUT_DIGEST_MISMATCH))
            for request, code in cases:
                with self.subTest(code=code), self.assertRaises(EnhancementError) as captured:
                    VideoEnhancementInterface().inspect_enhancement_request(request, now=NOW)
                self.assertEqual(captured.exception.code, code)

    def test_duration_is_profile_specific_not_a_platform_wide_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = enhancement_request(media)
            request["input"]["duration_seconds"] = 25
            request["workflow_profile"] = fake_workflow_profile("fake-enhancement-long-profile")

            result = VideoEnhancementInterface().inspect_enhancement_request(request, now=NOW)

        self.assertEqual(result["input_summary"]["duration_seconds"], 25.0)

    def test_profile_digest_nested_fields_operations_and_budget_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            requests = []
            bad_profile = enhancement_request(media)
            bad_profile["workflow_profile"]["media_limits"]["unknown"] = 1
            body = {key: value for key, value in bad_profile["workflow_profile"].items() if key != "profile_digest"}
            bad_profile["workflow_profile"]["profile_digest"] = digest(body)
            requests.append((bad_profile, EnhancementErrorCode.WORKFLOW_PROFILE_INVALID))
            duplicate = enhancement_request(media)
            duplicate["operations"].append({"type": "upscale", "factor": 2})
            requests.append((duplicate, EnhancementErrorCode.OPERATION_UNSUPPORTED))
            over_budget = enhancement_request(media)
            over_budget["budget"]["max_cost_usd"] = 0.001
            requests.append((over_budget, EnhancementErrorCode.BUDGET_EXCEEDED))
            unknown_profile = enhancement_request(media)
            unknown_profile["workflow_profile"]["profile_id"] = "caller-self-signed"
            body = {key: value for key, value in unknown_profile["workflow_profile"].items() if key != "profile_digest"}
            unknown_profile["workflow_profile"]["profile_digest"] = digest(body)
            requests.append((unknown_profile, EnhancementErrorCode.WORKFLOW_PROFILE_INVALID))
            for request, code in requests:
                with self.subTest(code=code), self.assertRaises(EnhancementError) as captured:
                    VideoEnhancementInterface().inspect_enhancement_request(request, now=NOW)
                self.assertEqual(captured.exception.code, code)

    def test_rights_source_class_is_allowlisted_and_bound_to_basis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = enhancement_request(media)
            request["input"]["rights"]["source_class"] = "user_asserted_other"
            with self.assertRaises(EnhancementError) as captured:
                VideoEnhancementInterface().inspect_enhancement_request(request, now=NOW)
        self.assertEqual(captured.exception.code, EnhancementErrorCode.RIGHTS_REJECTED)

    def test_oversize_file_is_rejected_by_stat_before_content_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "oversize.mp4"
            with media.open("wb") as stream:
                stream.seek(30 * 1024 * 1024)
                stream.write(b"x")
            request = enhancement_request(media)
            request["input"]["size_bytes"] = media.stat().st_size
            with self.assertRaises(EnhancementError) as captured:
                VideoEnhancementInterface().inspect_enhancement_request(request, now=NOW)
        self.assertEqual(captured.exception.code, EnhancementErrorCode.INPUT_TOO_LARGE)

    def test_sensitive_rights_metadata_is_rejected_without_echo(self) -> None:
        secret = "Bearer abcdefghijklmnopqrstuvwxyz012345"
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = enhancement_request(media)
            request["input"]["rights"]["fixture_provenance"] = secret
            with self.assertRaises(EnhancementError) as captured:
                VideoEnhancementInterface().inspect_enhancement_request(request, now=NOW)
        self.assertNotIn(secret, str(captured.exception))


if __name__ == "__main__":
    unittest.main()
