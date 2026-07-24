from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.storyboard_master_video_planning import VideoPlanningInterface
from ai_video_platform.skills.video_generation import VideoGenerationInterface
from ai_video_platform.skills.video_generation.cli import run_cli
from tests.skills.storyboard_master_video_planning.test_video_planning_interface import planning_request


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def execution_package() -> dict[str, object]:
    return VideoPlanningInterface().build_storyboard_master(planning_request())["artifacts"]["video_execution_package"]


def generation_request() -> dict[str, object]:
    package = execution_package()
    return {
        "execution_package": package,
        "approval_record": {"approval_id": "approval-001", "approval_type": "video_generation", "outcome": "approved", "authority": {"authority_id": "authorized-approval-boundary"}, "decided_at": "2026-07-20T08:00:00Z", "decision_ref": "review-decision-001", "subject_ref": {"digest": package["artifact_digest"]}, "valid_until": "2026-07-21T08:00:00Z"},
        "budget": {"estimated_cost_units": 10, "max_cost_units": 20, "max_requests": 2, "max_concurrency": 1, "max_attempts": 3, "timeout_seconds": 60},
        "provider_binding": {"binding_ref": "binding-001", "provider_id": "fake-video", "model_id": "model-001", "credential_ref": "secret://video/provider-credential"},
        "output": {"format": "mp4", "quality": "synthetic"}, "idempotency_key": "idem-video-001",
    }


NOW = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)


class VideoGenerationInterfaceTests(unittest.TestCase):
    def test_inspect_accepts_only_canonical_planning_artifact_bundle(self) -> None:
        result = VideoGenerationInterface().inspect_video_request(generation_request(), now=NOW)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["schema_version"], "1.0.0")
        self.assertEqual(result["contract_status"], "IDENTITY_REGISTERED_SCHEMA_PENDING")
        self.assertFalse(result["provider_execution_performed"])
        self.assertNotIn("credential_ref", result["provider_binding"])
        self.assertEqual(result["package_digest"], execution_package()["artifact_digest"])

    def test_inspect_is_deterministic_and_snapshots_input(self) -> None:
        request = generation_request()
        first = VideoGenerationInterface().inspect_video_request(request, now=NOW)
        second = VideoGenerationInterface().inspect_video_request(json.loads(json.dumps(request, sort_keys=True)), now=NOW)
        request["output"]["quality"] = "changed"
        self.assertEqual(first, second)
        self.assertEqual(first["output"], {"format": "mp4", "quality": "synthetic"})

    def test_cli_exposes_video_generation_run_alias_as_preflight(self) -> None:
        result = run_cli("run", generation_request(), now=NOW)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
