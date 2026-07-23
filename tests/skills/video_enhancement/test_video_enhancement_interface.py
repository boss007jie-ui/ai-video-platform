from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_enhancement import VideoEnhancementInterface
from ai_video_platform.skills.video_enhancement.preflight import fake_workflow_profile


NOW = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
SYNTHETIC_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomsynthetic-video"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def workflow_profile() -> dict[str, object]:
    return fake_workflow_profile()


def enhancement_request(path: Path, *, rights_basis: str = "SYNTHETIC") -> dict[str, object]:
    return {
        "authorization": {
            "authorization_id": "FTG-0-20260720-001",
            "work_item_id": "FT-05-002",
        },
        "input": {
            "path": str(path),
            "file_name": path.name,
            "size_bytes": len(SYNTHETIC_MP4),
            "sha256": "sha256:" + hashlib.sha256(SYNTHETIC_MP4).hexdigest(),
            "duration_seconds": 5,
            "width": 640,
            "height": 360,
            "fps": 30,
            "rights": {
                "basis": rights_basis,
                "lifecycle": "provider_eligible",
                "source_class": "synthetic_fixture",
                "fixture_provenance": "generated_for_ft_05_002",
            },
        },
        "workflow_profile": workflow_profile(),
        "operations": [
            {"type": "upscale", "factor": 2},
            {"type": "frame_interpolation", "factor": 2},
            {"type": "denoise_restore", "strength": 0.2},
        ],
        "budget": {
            "max_cost_usd": 0.02,
            "max_requests": 1,
            "max_concurrency": 1,
            "max_attempts": 3,
            "timeout_seconds": 120,
        },
        "idempotency_key": "ft-05-002-synthetic-001",
    }


class VideoEnhancementInterfaceTests(unittest.TestCase):
    def test_inspect_validates_local_media_rights_profile_operations_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = enhancement_request(media)
            first = VideoEnhancementInterface().inspect_enhancement_request(request, now=NOW)
            second = VideoEnhancementInterface().inspect_enhancement_request(
                json.loads(json.dumps(request)),
                now=NOW,
            )

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["schema_version"], "0.1.0")
        self.assertEqual(first["contract_status"], "DRAFT_UNREGISTERED")
        self.assertEqual(first["input_summary"]["file_name"], "synthetic-input.mp4")
        self.assertEqual(first["input_summary"]["format"], "mp4")
        self.assertEqual(first["input_summary"]["rights_basis"], "SYNTHETIC")
        self.assertEqual(first["input_summary"]["sha256"], request["input"]["sha256"])
        self.assertNotIn(str(media.parent), json.dumps(first))
        self.assertEqual([item["type"] for item in first["operations"]], [
            "upscale", "frame_interpolation", "denoise_restore",
        ])
        self.assertAlmostEqual(first["cost_estimate"]["estimated_cost_usd"], 0.0116666667, places=9)
        self.assertTrue(first["cost_estimate"]["estimate_only"])
        self.assertTrue(first["cost_estimate"]["not_a_quote"])
        self.assertFalse(first["provider_network_performed"])
        self.assertFalse(first["provider_execution_performed"])
        self.assertTrue(first["request_hash"].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
