from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_generation import (
    KieCredentialResolver,
    KieVideoProviderAdapter,
    VideoGenerationInterface,
)
from ai_video_platform.skills.video_generation.adapters import AdapterFailure
from ai_video_platform.skills.video_generation.kie_adapter import UrllibKieHttpTransport
from ai_video_platform.skills.video_generation.ledger import InMemoryVideoExecutionLedger
from tests.skills.video_generation.test_video_generation_interface import generation_request


NOW = datetime(2026, 7, 21, 4, 0, tzinfo=timezone.utc)


class RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.downloads: list[str] = []
        self.poll_responses: list[dict[str, object]] = [{
            "code": 200,
            "msg": "success",
            "data": {
                "taskId": "task_bytedance_safe_001",
                "model": "bytedance/seedance-2-mini",
                "state": "success",
                "param": "{}",
                "resultJson": '{"resultUrls":["https://files.example.test/result.mp4"]}',
                "failCode": "",
                "failMsg": "",
                "costTime": 1000,
                "completeTime": 1,
                "createTime": 1,
                "updateTime": 1,
                "progress": 100,
                "creditsConsumed": 3,
            },
        }]

    def request_json(
        self,
        method: str,
        path: str,
        api_key: str,
        *,
        payload: dict[str, object] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.requests.append({
            "method": method,
            "path": path,
            "api_key_present": bool(api_key),
            "payload": payload,
            "query": query,
        })
        if method == "POST":
            return {"code": 200, "msg": "success", "data": {"taskId": "task_bytedance_safe_001"}}
        return self.poll_responses.pop(0)

    def download(self, uri: str) -> bytes:
        self.downloads.append(uri)
        self.requests.append({"method": "DOWNLOAD"})
        return b"synthetic-kie-video"


def kie_request() -> dict[str, object]:
    request = generation_request()
    request["approval_record"]["decided_at"] = "2026-07-21T03:00:00Z"
    request["approval_record"]["valid_until"] = "2026-07-21T05:00:00Z"
    request["budget"] = {
        "estimated_cost_units": 3,
        "max_cost_units": 6,
        "max_requests": 1,
        "max_concurrency": 1,
        "max_attempts": 2,
        "timeout_seconds": 600,
    }
    request["provider_binding"] = {
        "binding_ref": "ftg-p-video-001",
        "provider_id": "kie",
        "model_id": "bytedance/seedance-2-mini",
        "credential_ref": "env://KIE_API_KEY",
    }
    request["output"] = {
        "format": "mp4",
        "prompt": "A static product on a clean table with a subtle camera push-in.",
        "reference_image_urls": [
            "https://assets.example.test/product-front.png",
            "https://assets.example.test/product-angle.png",
        ],
        "resolution": "480p",
        "aspect_ratio": "16:9",
        "duration": 6,
        "return_last_frame": False,
        "generate_audio": False,
        "web_search": False,
    }
    request["idempotency_key"] = "ftg-p-video-001-smoke"
    return request


class KieAdapterTests(unittest.TestCase):
    def test_default_http_transport_disables_api_redirects(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"code":200,"msg":"success","data":{}}'

        with patch("ai_video_platform.skills.video_generation.kie_adapter.build_opener") as build:
            build.return_value.open.return_value = Response()
            transport = UrllibKieHttpTransport()
            response = transport.request_json("GET", "/api/v1/jobs/recordInfo", "synthetic-value")

        self.assertEqual(response["code"], 200)
        redirect_handler = build.call_args.args[0]
        self.assertIsNone(redirect_handler.redirect_request(None, None, 302, None, None, None))

    def test_credential_resolver_reads_only_named_environment_entry(self) -> None:
        resolver = KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"})
        self.assertEqual(resolver.resolve(), "synthetic-value")
        with self.assertRaises(AdapterFailure) as captured:
            KieCredentialResolver(environ={}).resolve()
        self.assertEqual(captured.exception.code, "CREDENTIAL_UNAVAILABLE")
        self.assertNotIn("synthetic-value", str(captured.exception))

    def test_submit_builds_single_low_cost_multireference_task(self) -> None:
        transport = RecordingTransport()
        adapter = KieVideoProviderAdapter(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        interface = VideoGenerationInterface(adapter=adapter, ledger=InMemoryVideoExecutionLedger())

        submitted = interface.submit_video(kie_request(), now=NOW)

        self.assertEqual(submitted["state"], "submitted")
        self.assertTrue(submitted["provider_network_performed"])
        self.assertEqual(submitted["provider_execution_mode"], "kie_production")
        sent = transport.requests[0]
        self.assertEqual(sent["path"], "/api/v1/jobs/createTask")
        self.assertEqual(sent["payload"]["model"], "bytedance/seedance-2-mini")
        self.assertEqual(sent["payload"]["input"]["resolution"], "480p")
        self.assertEqual(sent["payload"]["input"]["duration"], 6)
        self.assertEqual(len(sent["payload"]["input"]["reference_image_urls"]), 2)
        self.assertNotIn("callBackUrl", sent["payload"])
        self.assertNotIn("synthetic-value", str(submitted))

    def test_poll_records_cost_and_download_returns_opaque_manifest_uri(self) -> None:
        transport = RecordingTransport()
        adapter = KieVideoProviderAdapter(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        ledger = InMemoryVideoExecutionLedger()
        interface = VideoGenerationInterface(adapter=adapter, ledger=ledger)
        submitted = interface.submit_video(kie_request(), now=NOW)

        succeeded = interface.poll_video(submitted["job_id"], now=NOW)
        downloaded = interface.download_video(submitted["job_id"], now=NOW)

        self.assertEqual(succeeded["provider_cost_units"], 3)
        self.assertEqual(
            [item["state"] for item in downloaded["history"]],
            ["submitting", "submitted", "polling", "succeeded", "downloaded"],
        )
        manifest = downloaded["asset_manifest_request"]
        self.assertEqual(manifest["contract_status"], "DRAFT_UNREGISTERED")
        self.assertEqual(manifest["uri"], "kie://task_bytedance_safe_001/video.mp4")
        self.assertEqual(manifest["size_bytes"], len(b"synthetic-kie-video"))
        self.assertEqual(transport.downloads, ["https://files.example.test/result.mp4"])
        self.assertNotIn("synthetic-value", str(ledger.get(submitted["job_id"])))

    def test_production_guardrails_reject_before_http(self) -> None:
        for mutate in (
            lambda request: request["output"].__setitem__("resolution", "720p"),
            lambda request: request["output"].__setitem__("duration", 7),
            lambda request: request["budget"].__setitem__("max_attempts", 3),
            lambda request: request["budget"].__setitem__("max_requests", 2),
            lambda request: request["output"].__setitem__("web_search", True),
        ):
            with self.subTest(mutate=mutate):
                request = kie_request()
                mutate(request)
                transport = RecordingTransport()
                adapter = KieVideoProviderAdapter(
                    transport=transport,
                    credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
                )
                interface = VideoGenerationInterface(adapter=adapter, ledger=InMemoryVideoExecutionLedger())
                with self.assertRaises(Exception):
                    interface.submit_video(request, now=NOW)
                self.assertEqual(transport.requests, [])

    def test_provider_failure_and_sensitive_messages_are_suppressed(self) -> None:
        class FailingTransport(RecordingTransport):
            def request_json(self, *args, **kwargs):
                raise RuntimeError("Bearer " + "S" * 24)

        adapter = KieVideoProviderAdapter(
            transport=FailingTransport(),
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        with self.assertRaises(AdapterFailure) as captured:
            adapter.submit(VideoGenerationInterface().inspect_video_request(kie_request(), now=NOW))
        self.assertNotIn("synthetic-value", str(captured.exception))
        self.assertNotIn("Bearer", str(captured.exception))

    def test_uncertain_submit_failure_is_not_retried(self) -> None:
        class UncertainTransport(RecordingTransport):
            def __init__(self) -> None:
                super().__init__()
                self.submit_count = 0

            def request_json(self, *args, **kwargs):
                self.submit_count += 1
                raise AdapterFailure("KIE_NETWORK_ERROR", "Synthetic uncertain outcome", retryable=True)

        transport = UncertainTransport()
        adapter = KieVideoProviderAdapter(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        interface = VideoGenerationInterface(adapter=adapter, ledger=InMemoryVideoExecutionLedger())
        with self.assertRaises(Exception):
            interface.submit_video(kie_request(), now=NOW)
        self.assertEqual(transport.submit_count, 1)

    def test_actual_cost_over_budget_fails_closed_before_download(self) -> None:
        transport = RecordingTransport()
        transport.poll_responses[0]["data"]["creditsConsumed"] = 7
        adapter = KieVideoProviderAdapter(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        ledger = InMemoryVideoExecutionLedger()
        interface = VideoGenerationInterface(adapter=adapter, ledger=ledger)
        submitted = interface.submit_video(kie_request(), now=NOW)

        with self.assertRaises(Exception):
            interface.poll_video(submitted["job_id"], now=NOW)

        record = ledger.get(submitted["job_id"])
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["error_code"], "BUDGET_EXCEEDED")
        self.assertEqual(record["provider_cost_units"], 7)
        self.assertEqual(transport.downloads, [])


if __name__ == "__main__":
    unittest.main()
