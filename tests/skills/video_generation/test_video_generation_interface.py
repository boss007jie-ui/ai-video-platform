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

from ai_video_platform.skills.video_generation import VideoGenerationInterface
from ai_video_platform.skills.video_generation.cli import run_cli


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def execution_package() -> dict[str, object]:
    master_body = {
        "artifact_name": "StoryboardMaster", "schema_version": "0.1.0", "contract_status": "DRAFT_UNREGISTERED",
        "task_id": "task-video-001",
        "source": {"storyboard_id": "storyboard-001", "storyboard_revision": 1, "storyboard_digest": "sha256:" + "1" * 64, "asset_manifest_id": "manifest-001", "asset_manifest_revision": 1, "asset_manifest_digest": "sha256:" + "2" * 64},
        "shots": [{"shot_id": "shot-001", "sequence": 1, "required_asset_roles": ["hero"], "continuity_group": "product", "visual_anchor": {"angle": "front"}, "motion": {"kind": "hold"}}],
        "asset_mapping": [{"shot_id": "shot-001", "role": "hero", "asset_id": "asset-001", "uri": "memory://asset.png", "sha256": "sha256:" + "3" * 64}],
        "visual_anchors": [{"continuity_group": "product", "anchor": {"angle": "front"}}],
        "motion_plan": [{"shot_id": "shot-001", "sequence": 1, "motion": {"kind": "hold"}}],
        "planning_provider_submission_performed": False,
    }
    master = {**master_body, "master_digest": digest(master_body)}
    source = dict(master_body["source"])
    package_body = {
        "artifact_name": "VideoExecutionPackage", "schema_version": "0.1.0", "contract_status": "DRAFT_UNREGISTERED",
        "package_id": "vep-" + digest(source).removeprefix("sha256:")[:20], "task_id": "task-video-001",
        "source": source, "storyboard_master": master, "asset_mapping": master_body["asset_mapping"],
        "visual_anchors": master_body["visual_anchors"], "motion_plan": master_body["motion_plan"],
        "planning_provider_submission_performed": False,
    }
    return {**package_body, "package_digest": digest(package_body)}


def generation_request() -> dict[str, object]:
    package = execution_package()
    return {
        "execution_package": package,
        "approval_record": {"approval_id": "approval-001", "approval_type": "video_generation", "outcome": "approved", "authority": {"authority_id": "authorized-approval-boundary"}, "decided_at": "2026-07-20T08:00:00Z", "decision_ref": "review-decision-001", "subject_ref": {"digest": package["package_digest"]}, "valid_until": "2026-07-21T08:00:00Z"},
        "budget": {"estimated_cost_units": 10, "max_cost_units": 20, "max_requests": 2, "max_concurrency": 1, "max_attempts": 3, "timeout_seconds": 60},
        "provider_binding": {"binding_ref": "binding-001", "provider_id": "fake-video", "model_id": "model-001", "credential_ref": "secret://video/provider-credential"},
        "output": {"format": "mp4", "quality": "synthetic"}, "idempotency_key": "idem-video-001",
    }


NOW = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)


class VideoGenerationInterfaceTests(unittest.TestCase):
    def test_inspect_preflight_is_deterministic_safe_and_provider_free(self) -> None:
        interface = VideoGenerationInterface()
        request = generation_request()
        first = interface.inspect_video_request(request, now=NOW)
        second = interface.inspect_video_request(json.loads(json.dumps(request, sort_keys=True)), now=NOW)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["schema_version"], "0.1.0")
        self.assertEqual(first["contract_status"], "DRAFT_UNREGISTERED")
        self.assertTrue(first["request_hash"].startswith("sha256:"))
        self.assertFalse(first["provider_execution_performed"])
        self.assertNotIn("credential_ref", first["provider_binding"])
        self.assertEqual(first["package_digest"], request["execution_package"]["package_digest"])

    def test_inspect_snapshots_caller_input(self) -> None:
        request = generation_request()
        result = VideoGenerationInterface().inspect_video_request(request, now=NOW)
        request["output"]["quality"] = "changed"
        self.assertEqual(result["output"], {"format": "mp4", "quality": "synthetic"})

    def test_cli_returns_stable_machine_readable_result(self) -> None:
        result = run_cli("inspect-video-request", generation_request(), now=NOW)
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "ready")

    def test_constructor_reserves_injected_adapter_and_ledger_seams(self) -> None:
        interface = VideoGenerationInterface(adapter=object(), ledger=object())
        result = interface.inspect_video_request(generation_request(), now=NOW)
        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["provider_execution_performed"])


if __name__ == "__main__":
    unittest.main()
