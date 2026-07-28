from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_enhancement import EnhancementError
from ai_video_platform.skills.video_enhancement.cli import execute_enhancement, main
from ai_video_platform.skills.video_enhancement.runninghub_adapter import (
    RunningHubCredentialResolver,
    RunningHubVideoEnhancementAdapter,
)
from ai_video_platform.skills.video_enhancement.runninghub_ledger import ARTIFACT_NAME, RECEIPT_NAME
from ai_video_platform.skills.video_enhancement.preflight import runninghub_workflow_profile
from tests.skills.video_enhancement.test_runninghub_adapter import (
    AiAppTransport,
    FakeClock,
    FakeTransport,
    SYNTHETIC_MP4,
    WORKFLOW_DIGEST,
)


def runninghub_request(path: Path) -> dict[str, object]:
    return {
        "authorization": {
            "authorization_id": "FTG-0-20260720-001",
            "work_item_id": "FT-05-003",
        },
        "input": {
            "path": str(path),
            "file_name": path.name,
            "size_bytes": len(SYNTHETIC_MP4),
            "sha256": "sha256:" + hashlib.sha256(SYNTHETIC_MP4).hexdigest(),
            "duration_seconds": 3,
            "width": 640,
            "height": 360,
            "fps": 24,
            "rights": {
                "basis": "SYNTHETIC",
                "lifecycle": "provider_eligible",
                "source_class": "synthetic_fixture",
                "fixture_provenance": "generated_for_ft_05_003",
            },
        },
        "workflow_profile": runninghub_workflow_profile(
            workflow_id="workflow-approved-001",
            workflow_json_sha256=WORKFLOW_DIGEST,
            input_node_id="10",
            input_field_name="video",
            node_info_list=[
                {"nodeId": "10", "fieldName": "video", "fieldValue": "UPLOAD_PLACEHOLDER"},
                {"nodeId": "20", "fieldName": "scale", "fieldValue": "2"},
            ],
            output_origins=["https://files.runninghub.ai"],
        ),
        "operations": [{"type": "upscale", "factor": 2}],
        "budget": {
            "max_cost_usd": 0.20,
            "max_requests": 1,
            "max_concurrency": 1,
            "max_attempts": 1,
            "timeout_seconds": 600,
        },
        "idempotency_key": "ft-05-003-runninghub-001",
    }


def runninghub_ai_app_request(path: Path) -> dict[str, object]:
    request = runninghub_request(path)
    request.pop("workflow_profile")
    request["provider_mode"] = "ai_app"
    request["idempotency_key"] = "ft-05-003-runninghub-ai-app-001"
    return request


class ReceiptAwareTransport(FakeTransport):
    def __init__(self, receipt_path: Path) -> None:
        super().__init__()
        self.receipt_path = receipt_path
        self.receipt_existed_before_download = False

    def download(self, uri: str, *, max_bytes: int) -> tuple[bytes, str]:
        self.receipt_existed_before_download = self.receipt_path.is_file()
        return super().download(uri, max_bytes=max_bytes)


class RunningHubCliTests(unittest.TestCase):
    @staticmethod
    def _adapter(transport: FakeTransport) -> RunningHubVideoEnhancementAdapter:
        clock = FakeClock()
        return RunningHubVideoEnhancementAdapter(
            transport=transport,
            credential_resolver=RunningHubCredentialResolver(environ={"RUNNINGHUB_API_KEY": "rh-test-credential-123"}),
            clock=clock,
            sleep=clock.sleep,
        )

    def test_default_enhance_is_rejecting_and_performs_no_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            with self.assertRaises(EnhancementError) as captured:
                execute_enhancement(runninghub_request(media), adapter_name="rejecting")
        self.assertEqual(captured.exception.code.value, "PROVIDER_REJECTED")

    def test_missing_key_preserves_credential_error_at_public_cli_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            transport = FakeTransport()
            adapter = RunningHubVideoEnhancementAdapter(
                transport=transport,
                credential_resolver=RunningHubCredentialResolver(environ={}),
            )
            with self.assertRaises(EnhancementError) as captured:
                execute_enhancement(
                    runninghub_request(media),
                    adapter_name="runninghub",
                    adapter=adapter,
                )
        self.assertEqual(captured.exception.code.value, "CREDENTIAL_UNAVAILABLE")
        self.assertEqual(captured.exception.details["adapter_code"], "CREDENTIAL_UNAVAILABLE")
        self.assertEqual(transport.network_calls, 0)

    def test_explicit_runninghub_persists_receipt_before_download_and_replays_locally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            receipt_path = media.parent / RECEIPT_NAME
            transport = ReceiptAwareTransport(receipt_path)
            request = runninghub_request(media)
            first = execute_enhancement(
                request,
                adapter_name="runninghub",
                adapter=self._adapter(transport),
            )

            replay_transport = FakeTransport(fail_stage="upload")
            replay = execute_enhancement(
                request,
                adapter_name="runninghub",
                adapter=self._adapter(replay_transport),
            )

            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            artifact = (media.parent / ARTIFACT_NAME).read_bytes()

        self.assertTrue(transport.receipt_existed_before_download)
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay_transport.network_calls, 0)
        self.assertEqual(artifact, SYNTHETIC_MP4)
        self.assertEqual(receipt["task_id"], "task-runninghub-12345678")
        self.assertEqual(receipt["task_cost_time"], 12.5)
        self.assertEqual(receipt["status_chain"], ["SUBMITTED", "RUNNING", "SUCCEEDED", "DOWNLOADED"])
        self.assertEqual(receipt["output_size_bytes"], len(SYNTHETIC_MP4))
        self.assertEqual(receipt["output_sha256"], "sha256:" + hashlib.sha256(SYNTHETIC_MP4).hexdigest())
        self.assertEqual(receipt["workflow_id"], "workflow-approved-001")
        self.assertEqual(receipt["workflow_json_sha256"], WORKFLOW_DIGEST)
        self.assertNotIn("signature=secret", json.dumps(receipt))

    def test_poll_failure_retains_pending_receipt_with_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = runninghub_request(media)

            with self.assertRaises(EnhancementError):
                execute_enhancement(
                    request,
                    adapter_name="runninghub",
                    adapter=self._adapter(FakeTransport(fail_stage="poll")),
                )

            receipt_path = media.parent / RECEIPT_NAME
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            artifact_exists = (media.parent / ARTIFACT_NAME).exists()

        self.assertFalse(artifact_exists)
        self.assertEqual(
            set(receipt),
            {"task_id", "idempotency_key", "request_hash", "submitted_at"},
        )
        self.assertEqual(receipt["task_id"], "task-runninghub-12345678")
        self.assertEqual(receipt["idempotency_key"], request["idempotency_key"])
        self.assertRegex(receipt["request_hash"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(receipt["submitted_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_ai_app_cli_injects_fixed_profile_records_config_and_replays_without_submit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = runninghub_ai_app_request(media)
            transport = AiAppTransport()

            first = execute_enhancement(
                request,
                adapter_name="runninghub",
                adapter=self._adapter(transport),
            )
            replay_transport = AiAppTransport(fail_stage="upload")
            replay = execute_enhancement(
                request,
                adapter_name="runninghub",
                adapter=self._adapter(replay_transport),
            )
            receipt = json.loads((media.parent / RECEIPT_NAME).read_text(encoding="utf-8"))

        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay_transport.network_calls, 0)
        self.assertEqual(receipt["provider_mode"], "ai_app")
        self.assertEqual(receipt["profile_id"], "runninghub-ai-app-video-enhance-v1")
        self.assertEqual(receipt["app_id"], "2066340206713851905")
        self.assertEqual(receipt["input_node_id"], "16")
        self.assertEqual(receipt["input_field_name"], "video")
        self.assertIsNone(receipt["workflow_id"])
        self.assertIsNone(receipt["workflow_json_sha256"])
        self.assertNotIn("signature=secret", json.dumps(receipt))

    def test_tampered_or_incomplete_evidence_fails_before_adapter_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = runninghub_request(media)
            execute_enhancement(request, adapter_name="runninghub", adapter=self._adapter(FakeTransport()))
            receipt_path = media.parent / RECEIPT_NAME
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["task_cost_time"] = 999
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            transport = FakeTransport(fail_stage="upload")
            with self.assertRaises(EnhancementError) as captured:
                execute_enhancement(request, adapter_name="runninghub", adapter=self._adapter(transport))
        self.assertEqual(captured.exception.code.value, "IDEMPOTENCY_MISMATCH")
        self.assertEqual(transport.network_calls, 0)

    def test_cli_accepts_explicit_fake_and_keeps_other_commands_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request_path = media.parent / "request.json"
            request_path.write_text(json.dumps(runninghub_request(media)), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["enhance", str(request_path), "--adapter", "fake"])
            payload = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["adapter"], "fake")


if __name__ == "__main__":
    unittest.main()
