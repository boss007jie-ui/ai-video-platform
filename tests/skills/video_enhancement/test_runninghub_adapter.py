from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import ai_video_platform.skills.video_enhancement as public_surface
from ai_video_platform.skills.video_enhancement.adapters import AdapterFailure
from ai_video_platform.skills.video_enhancement.runninghub_adapter import (
    RunningHubCredentialResolver,
    RunningHubVideoEnhancementAdapter,
)


SYNTHETIC_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomrunninghub-test"
WORKFLOW_DIGEST = "sha256:" + "a" * 64


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class FakeTransport:
    def __init__(
        self,
        *,
        poll_responses: list[object] | None = None,
        download_content: bytes = SYNTHETIC_MP4,
        download_content_type: str = "video/mp4",
        fail_stage: str | None = None,
    ) -> None:
        self.poll_responses = list(poll_responses or [
            {"data": {"status": "RUNNING"}},
            {"data": [{
                "fileUrl": "https://files.runninghub.ai/output/final.mp4?signature=secret",
                "fileType": "mp4",
                "taskCostTime": 12.5,
            }]},
        ])
        self.download_content = download_content
        self.download_content_type = download_content_type
        self.fail_stage = fail_stage
        self.calls: list[tuple[str, object]] = []

    @property
    def network_calls(self) -> int:
        return len(self.calls)

    def upload_multipart(self, credential: str, *, file_name: str, file_bytes: bytes, media_type: str) -> dict[str, object]:
        self.calls.append(("upload", {"credential": credential, "file_name": file_name, "media_type": media_type}))
        if self.fail_stage == "upload":
            raise AdapterFailure("UPLOAD_FAILED", "synthetic upload failure", retryable=False)
        return {"data": {"fileName": "api/test/input.mp4", "fileType": "video"}}

    def request_json(self, method: str, path: str, credential: str, *, payload: dict[str, object]) -> object:
        self.calls.append((path, payload))
        if path == "/task/openapi/create":
            if self.fail_stage == "create":
                raise AdapterFailure("CREATE_FAILED", "synthetic create failure", retryable=False)
            return {"data": {"taskId": "task-runninghub-12345678"}}
        if self.fail_stage == "poll":
            raise AdapterFailure("POLL_FAILED", "synthetic poll failure", retryable=False)
        return self.poll_responses.pop(0)

    def download(self, uri: str, *, max_bytes: int) -> tuple[bytes, str]:
        self.calls.append(("download", uri))
        if self.fail_stage == "download":
            raise AdapterFailure("DOWNLOAD_FAILED", "synthetic download failure", retryable=False)
        if len(self.download_content) > max_bytes:
            return self.download_content, self.download_content_type
        return self.download_content, self.download_content_type


def request_for(path: Path, *, include_workflow_id: bool = True, include_digest: bool = True) -> dict[str, object]:
    binding: dict[str, object] = {
        "input_node_id": "10",
        "input_field_name": "video",
        "node_info_list": [
            {"nodeId": "10", "fieldName": "video", "fieldValue": "UPLOAD_PLACEHOLDER"},
            {"nodeId": "20", "fieldName": "scale", "fieldValue": "2"},
        ],
        "output_origins": ["https://files.runninghub.ai"],
    }
    if include_workflow_id:
        binding["workflow_id"] = "workflow-approved-001"
    if include_digest:
        binding["workflow_json_sha256"] = WORKFLOW_DIGEST
    return {
        "request_hash": "sha256:" + hashlib.sha256(b"request").hexdigest(),
        "idempotency_key": "runninghub-test-001",
        "input": {
            "path": str(path),
            "file_name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        },
        "workflow_profile": {"workflow_binding": binding},
    }


class RunningHubAdapterTests(unittest.TestCase):
    def _adapter(self, transport: FakeTransport, clock: FakeClock | None = None, **kwargs: object) -> RunningHubVideoEnhancementAdapter:
        fake_clock = clock or FakeClock()
        return RunningHubVideoEnhancementAdapter(
            transport=transport,
            credential_resolver=RunningHubCredentialResolver(environ={"RUNNINGHUB_API_KEY": "rh-test-credential-123"}),
            clock=fake_clock,
            sleep=fake_clock.sleep,
            **kwargs,
        )

    def test_missing_credential_and_unfixed_profile_fail_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            missing_key_transport = FakeTransport()
            missing_key = RunningHubVideoEnhancementAdapter(
                transport=missing_key_transport,
                credential_resolver=RunningHubCredentialResolver(environ={}),
            )
            with self.assertRaises(AdapterFailure) as key_error:
                missing_key.submit(request_for(media))

            for field in ("workflow_id", "workflow_json_sha256"):
                transport = FakeTransport()
                adapter = self._adapter(transport)
                request = request_for(
                    media,
                    include_workflow_id=field != "workflow_id",
                    include_digest=field != "workflow_json_sha256",
                )
                with self.subTest(field=field), self.assertRaises(AdapterFailure) as profile_error:
                    adapter.submit(request)
                self.assertEqual(profile_error.exception.code, "WORKFLOW_PROFILE_INVALID")
                self.assertEqual(transport.network_calls, 0)

        self.assertEqual(key_error.exception.code, "CREDENTIAL_UNAVAILABLE")
        self.assertEqual(missing_key_transport.network_calls, 0)

    def test_upload_create_poll_download_chain_is_strict_and_complete(self) -> None:
        transport = FakeTransport()
        clock = FakeClock()
        adapter = self._adapter(transport, clock)
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            task_id = adapter.submit(request_for(media))
            running = adapter.poll(task_id)
            succeeded = adapter.poll(task_id)
            artifact = adapter.download(task_id)

        self.assertEqual(task_id, "task-runninghub-12345678")
        self.assertEqual(running, {"state": "running", "status": "RUNNING"})
        self.assertEqual(succeeded["state"], "succeeded")
        self.assertEqual(succeeded["task_cost_time"], 12.5)
        self.assertEqual(clock.sleeps, [5.0])
        create_payload = transport.calls[1][1]
        self.assertEqual(create_payload["workflowId"], "workflow-approved-001")
        self.assertEqual(create_payload["nodeInfoList"][0]["fieldValue"], "api/test/input.mp4")
        self.assertFalse({"instanceType", "webhookUrl", "usePersonalQueue", "retainSeconds"} & set(create_payload))
        self.assertEqual(artifact["content"], SYNTHETIC_MP4)
        self.assertEqual(artifact["media_type"], "video/mp4")
        self.assertEqual(artifact["sha256"], "sha256:" + hashlib.sha256(SYNTHETIC_MP4).hexdigest())
        self.assertEqual(adapter.status_chain, ("SUBMITTED", "RUNNING", "SUCCEEDED", "DOWNLOADED"))
        self.assertEqual(adapter.network_calls, 5)

    def test_failed_poll_stops_and_does_not_download(self) -> None:
        transport = FakeTransport(poll_responses=[{"data": {"status": "FAILED", "error": "safe failure"}}])
        adapter = self._adapter(transport)
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            task_id = adapter.submit(request_for(media))
            failed = adapter.poll(task_id)
            with self.assertRaises(AdapterFailure) as captured:
                adapter.download(task_id)

        self.assertEqual(failed["state"], "failed")
        self.assertEqual(captured.exception.code, "DOWNLOAD_NOT_READY")
        self.assertNotIn("download", [item[0] for item in transport.calls])

    def test_wss_running_shape_is_ignored_until_outputs_arrive(self) -> None:
        transport = FakeTransport(poll_responses=[
            {"data": {"clientId": "client-1", "wssUrl": "wss://ignored.invalid/task"}},
            {"data": [{
                "fileUrl": "https://files.runninghub.ai/output/final.mp4",
                "fileType": "mp4",
                "taskCostTime": 2,
            }]},
        ])
        adapter = self._adapter(transport)
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            task_id = adapter.submit(request_for(media))
            running = adapter.poll(task_id)
            succeeded = adapter.poll(task_id)
        self.assertEqual(running, {"state": "running", "status": "RUNNING"})
        self.assertEqual(succeeded["state"], "succeeded")

    def test_unknown_status_with_outputs_still_fails_closed(self) -> None:
        transport = FakeTransport(poll_responses=[{
            "status": "UNKNOWN_PROVIDER_STATE",
            "data": [{
                "fileUrl": "https://files.runninghub.ai/output/final.mp4",
                "fileType": "mp4",
                "taskCostTime": 2,
            }],
        }])
        adapter = self._adapter(transport)
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            task_id = adapter.submit(request_for(media))
            with self.assertRaises(AdapterFailure) as captured:
                adapter.poll(task_id)
        self.assertEqual(captured.exception.code, "RESPONSE_INVALID")

    def test_poll_limits_and_timeout_are_enforced_without_extra_calls(self) -> None:
        transport = FakeTransport(poll_responses=[{"data": {"status": "RUNNING"}}] * 3)
        clock = FakeClock()
        adapter = self._adapter(transport, clock, max_polls=2)
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            task_id = adapter.submit(request_for(media))
            adapter.poll(task_id)
            adapter.poll(task_id)
            with self.assertRaises(AdapterFailure) as poll_limit:
                adapter.poll(task_id)
        self.assertEqual(poll_limit.exception.code, "POLL_LIMIT_EXCEEDED")
        self.assertEqual([item[0] for item in transport.calls].count("/task/openapi/outputs"), 2)

        timeout_transport = FakeTransport()
        timeout_clock = FakeClock()
        timeout_adapter = self._adapter(timeout_transport, timeout_clock, timeout_seconds=600)
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            task_id = timeout_adapter.submit(request_for(media))
            timeout_clock.value += 601
            with self.assertRaises(AdapterFailure) as timeout_error:
                timeout_adapter.poll(task_id)
        self.assertEqual(timeout_error.exception.code, "TIMEOUT")
        self.assertEqual([item[0] for item in timeout_transport.calls].count("/task/openapi/outputs"), 0)

    def test_each_transport_failure_stops_without_retry(self) -> None:
        for stage in ("upload", "create", "poll", "download"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                media = Path(directory) / "input.mp4"
                media.write_bytes(SYNTHETIC_MP4)
                transport = FakeTransport(fail_stage=stage, poll_responses=[{
                    "data": [{
                        "fileUrl": "https://files.runninghub.ai/output/final.mp4",
                        "fileType": "mp4",
                        "taskCostTime": 1,
                    }],
                }])
                adapter = self._adapter(transport)
                with self.assertRaises(AdapterFailure) as captured:
                    task_id = adapter.submit(request_for(media))
                    adapter.poll(task_id)
                    adapter.download(task_id)
                stage_calls = [item[0] for item in transport.calls]
                target = {
                    "upload": "upload",
                    "create": "/task/openapi/create",
                    "poll": "/task/openapi/outputs",
                    "download": "download",
                }[stage]
                self.assertEqual(stage_calls.count(target), 1)
                self.assertEqual(captured.exception.code, f"{stage.upper()}_FAILED")

    def test_input_and_output_bytes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "input.txt"
            wrong.write_bytes(SYNTHETIC_MP4)
            transport = FakeTransport()
            with self.assertRaises(AdapterFailure) as input_error:
                self._adapter(transport).submit(request_for(wrong))
            self.assertEqual(input_error.exception.code, "INPUT_FILE_INVALID")
            self.assertEqual(transport.network_calls, 0)

            media = Path(directory) / "input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            bad_output = FakeTransport(
                poll_responses=[{"data": [{
                    "fileUrl": "https://files.runninghub.ai/output/final.mp4",
                    "fileType": "mp4",
                    "taskCostTime": 1,
                }]}],
                download_content=b"not-an-mp4",
            )
            adapter = self._adapter(bad_output)
            task_id = adapter.submit(request_for(media))
            adapter.poll(task_id)
            with self.assertRaises(AdapterFailure) as output_error:
                adapter.download(task_id)
            self.assertEqual(output_error.exception.code, "DOWNLOAD_INVALID")

            wrong_type = FakeTransport(
                poll_responses=[{"data": [{
                    "fileUrl": "https://files.runninghub.ai/output/final.mp4",
                    "fileType": "mp4",
                    "taskCostTime": 1,
                }]}],
                download_content_type="application/octet-stream",
            )
            adapter = self._adapter(wrong_type)
            task_id = adapter.submit(request_for(media))
            adapter.poll(task_id)
            with self.assertRaises(AdapterFailure) as type_error:
                adapter.download(task_id)
            self.assertEqual(type_error.exception.code, "DOWNLOAD_INVALID")

            oversized = FakeTransport(
                poll_responses=[{"data": [{
                    "fileUrl": "https://files.runninghub.ai/output/final.mp4",
                    "fileType": "mp4",
                    "taskCostTime": 1,
                }]}],
            )
            adapter = self._adapter(oversized, max_output_bytes=len(SYNTHETIC_MP4) - 1)
            task_id = adapter.submit(request_for(media))
            adapter.poll(task_id)
            with self.assertRaises(AdapterFailure) as size_error:
                adapter.download(task_id)
            self.assertEqual(size_error.exception.code, "DOWNLOAD_INVALID")

    def test_public_surface_exports_only_real_and_fake_runninghub_adapters(self) -> None:
        self.assertIs(public_surface.RunningHubVideoEnhancementAdapter, RunningHubVideoEnhancementAdapter)
        self.assertIn("FakeRunningHubVideoEnhancementAdapter", public_surface.__all__)
        self.assertNotIn("RunningHubCredentialResolver", public_surface.__all__)
        self.assertFalse(any(name.endswith("Transport") for name in public_surface.__all__))


if __name__ == "__main__":
    unittest.main()
