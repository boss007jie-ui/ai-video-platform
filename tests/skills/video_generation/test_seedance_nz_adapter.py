from __future__ import annotations

import ast
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


from ai_video_platform.skills.video_generation.seedance_nz_adapter import (
    AUTHORIZATION_ID,
    MODEL_ID,
    FakeSeedanceNzFileUploader,
    FakeSeedanceNzVideoProviderAdapter,
    SeedanceNzCredentialResolver,
    SeedanceNzFileUploader,
    SeedanceNzVideoProviderAdapter,
    UrllibSeedanceNzHttpTransport,
)
from ai_video_platform.skills.video_generation.adapters import AdapterFailure


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.response: dict[str, object] = {"task_id": "0123456789abcdef0123456789abcdef"}
        self.failure: AdapterFailure | None = None
        self.download_calls: list[str] = []
        self.download_content = b"production-video"
        self.upload_calls: list[dict[str, object]] = []
        self.upload_response: dict[str, object] = {
            "url": "https://files.example/reference.png",
            "file_type": "image",
            "size": 3,
            "expires_in": 86400,
        }
        self.upload_failure: AdapterFailure | None = None

    def request_json(
        self,
        method: str,
        path: str,
        credential: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append({"method": method, "path": path, "credential": credential, "payload": payload})
        if self.failure is not None:
            raise self.failure
        return dict(self.response)

    def download(self, uri: str) -> bytes:
        self.download_calls.append(uri)
        return self.download_content

    def upload_multipart(
        self,
        credential: str,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
    ) -> dict[str, object]:
        self.upload_calls.append({
            "credential": credential,
            "file_name": file_name,
            "file_bytes": file_bytes,
            "media_type": media_type,
        })
        if self.upload_failure is not None:
            raise self.upload_failure
        return dict(self.upload_response)


class AdvancingTransport(RecordingTransport):
    def __init__(self, now: list[float]) -> None:
        super().__init__()
        self._now = now

    def request_json(
        self,
        method: str,
        path: str,
        credential: str,
        *,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response = super().request_json(method, path, credential, payload=payload)
        if method == "GET":
            self._now[0] = 601.0
        return response


class FakeHttpResponse:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return self._body


class RecordingOpener:
    def __init__(self, responses: list[FakeHttpResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def open(self, request: object, *, timeout: float) -> FakeHttpResponse:
        self.calls.append({"request": request, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SeedanceNzFakeAdapterTests(unittest.TestCase):
    def test_fake_adapter_is_deterministic_and_never_uses_network(self) -> None:
        adapter = FakeSeedanceNzVideoProviderAdapter(
            poll_statuses=("queued", "in_progress", "completed"),
        )
        request = {"request_hash": "sha256:request", "idempotency_key": "idem-001"}

        job_id = adapter.submit(request)
        self.assertEqual(AUTHORIZATION_ID, "FTG-P-VIDEO-003")
        self.assertEqual(MODEL_ID, "seedance-2.0-fast-multi")
        self.assertTrue(job_id.startswith("fake-sd-nz-"))
        self.assertEqual(adapter.poll(job_id), {"state": "running", "status": "queued", "progress": 0})
        self.assertEqual(adapter.poll(job_id), {"state": "running", "status": "in_progress", "progress": 50})
        self.assertEqual(adapter.poll(job_id), {"state": "succeeded", "status": "completed", "progress": 100})

        artifact = adapter.download(job_id)
        self.assertEqual(artifact["content"], b"synthetic-mp4")
        self.assertEqual(artifact["content_type"], "video/mp4")
        self.assertEqual(
            artifact["sha256"],
            "sha256:" + hashlib.sha256(b"synthetic-mp4").hexdigest(),
        )
        self.assertEqual(adapter.network_calls, 0)

    def test_fake_image_submit_is_deterministic_and_never_uses_network(self) -> None:
        adapter = FakeSeedanceNzVideoProviderAdapter()
        request = {"prompt": "High-end skincare product", "idempotency_key": "img-001"}

        first = adapter.submit_image(request)
        second = adapter.submit_image(request)

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("fake-sd-nz-img-"))
        self.assertEqual(adapter.network_calls, 0)

    def test_fake_image_poll_advances_to_success(self) -> None:
        adapter = FakeSeedanceNzVideoProviderAdapter(
            image_poll_statuses=("SUBMITTED", "IN_PROGRESS", "SUCCESS"),
        )
        job_id = adapter.submit_image({"prompt": "High-end skincare product"})

        self.assertEqual(adapter.poll_image(job_id)["data"]["status"], "SUBMITTED")
        self.assertEqual(adapter.poll_image(job_id)["data"]["status"], "IN_PROGRESS")
        completed = adapter.poll_image(job_id)

        self.assertEqual(completed["code"], "success")
        self.assertEqual(completed["data"]["status"], "SUCCESS")
        self.assertEqual(completed["data"]["result_url"], f"fake://{job_id}.jpeg")
        self.assertEqual(adapter.network_calls, 0)

    def test_fake_image_download_returns_deterministic_jpeg(self) -> None:
        adapter = FakeSeedanceNzVideoProviderAdapter(image_poll_statuses=("SUCCESS",))
        job_id = adapter.submit_image({"prompt": "High-end skincare product"})
        adapter.poll_image(job_id)

        artifact = adapter.download_image(job_id)

        self.assertEqual(artifact["bytes"], b"synthetic-jpeg")
        self.assertEqual(artifact["content_type"], "image/jpeg")
        self.assertEqual(
            artifact["sha256"],
            "sha256:" + hashlib.sha256(b"synthetic-jpeg").hexdigest(),
        )
        self.assertEqual(adapter.network_calls, 0)

    def test_fake_failures_cancel_and_corrupt_download_are_injectable(self) -> None:
        adapter = FakeSeedanceNzVideoProviderAdapter(submit_failures=1)
        request = {"request_hash": "sha256:request", "idempotency_key": "idem-001"}
        with self.assertRaises(AdapterFailure) as submit:
            adapter.submit(request)
        self.assertEqual(submit.exception.code, "PROVIDER_FORBIDDEN")

        adapter = FakeSeedanceNzVideoProviderAdapter(
            poll_statuses=("completed",),
            poll_failures=1,
            corrupt_download=True,
        )
        job_id = adapter.submit(request)
        with self.assertRaises(AdapterFailure) as poll:
            adapter.poll(job_id)
        self.assertEqual(poll.exception.code, "PROVIDER_FORBIDDEN")
        self.assertEqual(adapter.poll(job_id)["state"], "succeeded")
        self.assertEqual(adapter.download(job_id)["sha256"], "sha256:" + "0" * 64)
        with self.assertRaises(AdapterFailure) as cancel:
            adapter.cancel(job_id)
        self.assertEqual(cancel.exception.code, "CANCEL_NOT_SUPPORTED")
        self.assertEqual(adapter.network_calls, 0)


class SeedanceNzProductionAdapterTests(unittest.TestCase):
    def _request(self, *, seconds: object = 5) -> dict[str, object]:
        return {
            "request_hash": "sha256:request",
            "idempotency_key": "idem-001",
            "output": {
                "model": "must-not-override",
                "prompt": "Replace @Video 1 with @Image 1",
                "seconds": seconds,
                "metadata": {
                    "resolution": "must-not-override",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "https://assets.example/image.png"}},
                        {"type": "video_url", "video_url": {"url": "https://assets.example/video.mp4"}},
                    ],
                },
            },
        }

    def test_submit_uses_fixed_endpoint_model_and_string_seconds(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )

        job_id = adapter.submit(self._request(seconds=5))

        self.assertEqual(job_id, "0123456789abcdef0123456789abcdef")
        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual((call["method"], call["path"]), ("POST", "/v1/videos"))
        self.assertEqual(
            call["payload"],
            {
                "model": "seedance-2.0-fast-multi",
                "prompt": "Replace @Video 1 with @Image 1",
                "seconds": "5",
                "metadata": {
                    "resolution": "480p",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "https://assets.example/image.png"}},
                        {"type": "video_url", "video_url": {"url": "https://assets.example/video.mp4"}},
                    ],
                },
            },
        )
        self.assertIsInstance(call["payload"]["seconds"], str)
        self.assertEqual(adapter.network_calls, 1)

    def test_submit_orders_storyboard_panels_then_products_then_master_sheet(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        request = self._request()
        request["output"]["metadata"]["content"] = [
            {
                "type": "image_url",
                "reference_role": "storyboard_structure_reference",
                "image_url": {"url": "https://assets.example/storyboard-sheet.png"},
            },
            {
                "type": "image_url",
                "reference_role": "product_reference",
                "image_url": {"url": "https://assets.example/product-front.png"},
            },
            {
                "type": "image_url",
                "reference_role": "production_panel",
                "image_url": {"url": "https://assets.example/panel-s01-p01.png"},
            },
            {
                "type": "image_url",
                "reference_role": "production_panel",
                "image_url": {"url": "https://assets.example/panel-s01-p02.png"},
            },
            {
                "type": "image_url",
                "reference_role": "product_reference",
                "image_url": {"url": "https://assets.example/product-detail.png"},
            },
        ]

        adapter.submit(request)

        self.assertEqual(
            transport.calls[0]["payload"]["metadata"]["content"],
            [
                {"type": "image_url", "image_url": {"url": "https://assets.example/panel-s01-p01.png"}},
                {"type": "image_url", "image_url": {"url": "https://assets.example/panel-s01-p02.png"}},
                {"type": "image_url", "image_url": {"url": "https://assets.example/product-front.png"}},
                {"type": "image_url", "image_url": {"url": "https://assets.example/product-detail.png"}},
                {"type": "image_url", "image_url": {"url": "https://assets.example/storyboard-sheet.png"}},
            ],
        )

    def test_missing_credential_and_invalid_seconds_fail_before_network(self) -> None:
        transport = RecordingTransport()
        with patch.dict(os.environ, {}, clear=True):
            adapter = SeedanceNzVideoProviderAdapter(transport=transport)
            with self.assertRaises(AdapterFailure) as missing:
                adapter.submit(self._request())
        self.assertEqual(missing.exception.code, "CREDENTIAL_UNAVAILABLE")
        self.assertEqual(transport.calls, [])

        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        for seconds in (True, 1.5, "five", 0):
            with self.subTest(seconds=seconds):
                with self.assertRaises(AdapterFailure) as invalid:
                    adapter.submit(self._request(seconds=seconds))
                self.assertEqual(invalid.exception.code, "REQUEST_INVALID")
        self.assertEqual(transport.calls, [])

    def test_unauthorized_submit_is_non_retryable_and_redacted(self) -> None:
        transport = RecordingTransport()
        credential = "sk-test-key"
        transport.failure = AdapterFailure(
            "PROVIDER_FORBIDDEN",
            "Seedance.nz rejected " + credential,
            retryable=False,
            http_status=401,
            provider_error_summary={"authorization": credential},
        )
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": credential},
            ),
        )

        with self.assertRaises(AdapterFailure) as captured:
            adapter.submit(self._request())

        self.assertEqual(captured.exception.code, "PROVIDER_FORBIDDEN")
        self.assertFalse(captured.exception.retryable)
        self.assertEqual(captured.exception.http_status, 401)
        self.assertNotIn(credential, str(captured.exception))
        self.assertNotIn(credential, str(captured.exception.provider_error_summary))

    def test_poll_maps_provider_states_and_downloads_completed_artifact(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        task_id = adapter.submit(self._request())

        transport.response = {"status": "queued"}
        self.assertEqual(adapter.poll(task_id), {"state": "running", "status": "queued", "progress": 0})
        transport.response = {"status": "in_progress", "progress": 37}
        self.assertEqual(adapter.poll(task_id), {"state": "running", "status": "in_progress", "progress": 37})
        transport.response = {
            "status": "completed",
            "progress": 100,
            "metadata": {"url": "https://download.example/signed-video.mp4", "width": 480},
        }
        self.assertEqual(adapter.poll(task_id), {"state": "succeeded", "status": "completed", "progress": 100})
        self.assertEqual(
            (transport.calls[-1]["method"], transport.calls[-1]["path"]),
            ("GET", f"/v1/videos/{task_id}"),
        )

        artifact = adapter.download(task_id)
        self.assertEqual(artifact["content"], b"production-video")
        self.assertEqual(artifact["content_type"], "video/mp4")
        self.assertEqual(
            artifact["sha256"],
            "sha256:" + hashlib.sha256(b"production-video").hexdigest(),
        )
        self.assertEqual(transport.download_calls, ["https://download.example/signed-video.mp4"])

    def test_poll_maps_nested_task_dto_states_progress_and_result_url(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        task_id = adapter.submit(self._request())

        transport.response = {"data": {"status": "SUBMITTED", "progress": 0}}
        self.assertEqual(
            adapter.poll(task_id),
            {"state": "running", "status": "submitted", "progress": 0},
        )
        transport.response = {"data": {"status": "IN_PROGRESS", "progress": "50%"}}
        self.assertEqual(
            adapter.poll(task_id),
            {"state": "running", "status": "in_progress", "progress": 50},
        )
        transport.response = {
            "data": {
                "status": "SUCCESS",
                "progress": 99,
                "result_url": "https://download.example/nested-video.mp4?signature=opaque",
            },
        }

        completed = adapter.poll(task_id)

        self.assertEqual(completed, {"state": "succeeded", "status": "success", "progress": 100})
        adapter.download(task_id)
        self.assertEqual(
            transport.download_calls,
            ["https://download.example/nested-video.mp4?signature=opaque"],
        )

    def test_poll_maps_unknown_initial_state_then_completed(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        task_id = adapter.submit(self._request())
        transport.response = {"status": "unknown"}

        self.assertEqual(
            adapter.poll(task_id),
            {"state": "running", "status": "submitted", "progress": 0},
        )

        transport.response = {
            "status": "completed",
            "progress": 100,
            "metadata": {"url": "https://download.example/completed-after-unknown.mp4"},
        }
        self.assertEqual(
            adapter.poll(task_id),
            {"state": "succeeded", "status": "completed", "progress": 100},
        )

    def test_poll_uses_nested_video_url_fallback(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        task_id = adapter.submit(self._request())
        transport.response = {
            "data": {
                "status": "success",
                "data": {
                    "content": {
                        "video_url": "https://download.example/nested-content-video.mp4",
                    },
                },
            },
        }

        completed = adapter.poll(task_id)

        self.assertEqual(completed["state"], "succeeded")
        self.assertEqual(completed["status"], "success")
        adapter.download(task_id)
        self.assertEqual(transport.download_calls, ["https://download.example/nested-content-video.mp4"])

    def test_poll_status_matching_is_case_insensitive_and_normalized(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        task_id = adapter.submit(self._request())

        transport.response = {"status": "QuEuEd"}
        self.assertEqual(
            adapter.poll(task_id),
            {"state": "running", "status": "queued", "progress": 0},
        )
        transport.response = {
            "status": "CoMpLeTeD",
            "metadata": {"url": "https://download.example/mixed-case.mp4"},
        }
        completed = adapter.poll(task_id)
        self.assertEqual(completed, {"state": "succeeded", "status": "completed", "progress": 100})

    def test_nested_progress_percent_is_strict_and_fail_closed(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        task_id = adapter.submit(self._request())
        transport.response = {"data": {"status": "IN_PROGRESS", "progress": "50 %"}}

        with self.assertRaises(AdapterFailure) as malformed:
            adapter.poll(task_id)

        self.assertEqual(malformed.exception.code, "RESPONSE_INVALID")
        diagnostic = json.loads(malformed.exception.provider_error_summary)
        self.assertEqual(diagnostic["raw_status"], "IN_PROGRESS")
        self.assertEqual(diagnostic["response_keys"], ["data"])
        self.assertEqual(diagnostic["nested_data_keys"], ["progress", "status"])

    def test_nested_failure_is_terminal_and_never_downloads(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        task_id = adapter.submit(self._request())
        transport.response = {
            "data": {
                "status": "FAILURE",
                "error": {"code": "content_policy", "message": "request rejected"},
            },
        }

        result = adapter.poll(task_id)

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["progress"], 100)
        with self.assertRaises(AdapterFailure) as download:
            adapter.download(task_id)
        self.assertEqual(download.exception.code, "DOWNLOAD_NOT_READY")
        self.assertEqual(transport.download_calls, [])

    def test_unknown_poll_status_preserves_only_safe_diagnostic_shape(self) -> None:
        credential = "sk-test-key"
        signed_url = "https://download.example/video.mp4?signature=super-secret"
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": credential},
            ),
        )
        task_id = adapter.submit(self._request())
        transport.response = {
            "status": "MYSTERY_STATE",
            "authorization": credential,
            "metadata": {"url": signed_url},
            "data": {
                "status": "MYSTERY_STATE",
                "progress": 10,
                "api_key": credential,
            },
        }

        with self.assertRaises(AdapterFailure) as unsupported:
            adapter.poll(task_id)

        self.assertEqual(unsupported.exception.code, "RESPONSE_INVALID")
        summary = unsupported.exception.provider_error_summary
        diagnostic = json.loads(summary)
        self.assertEqual(diagnostic["raw_status"], "MYSTERY_STATE")
        self.assertIn("status", diagnostic["response_keys"])
        self.assertIn("metadata", diagnostic["response_keys"])
        self.assertIn("status", diagnostic["nested_data_keys"])
        self.assertIn("progress", diagnostic["nested_data_keys"])
        self.assertNotIn(credential, summary)
        self.assertNotIn(signed_url, summary)
        self.assertNotIn("authorization", summary.lower())
        self.assertNotIn("api_key", summary.lower())

    def test_non_string_poll_status_fails_closed_with_null_raw_status(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        task_id = adapter.submit(self._request())
        transport.response = {"data": {"status": 7, "progress": 0}}

        with self.assertRaises(AdapterFailure) as invalid:
            adapter.poll(task_id)

        self.assertEqual(invalid.exception.code, "RESPONSE_INVALID")
        diagnostic = json.loads(invalid.exception.provider_error_summary)
        self.assertIsNone(diagnostic["raw_status"])
        self.assertEqual(diagnostic["response_keys"], ["data"])
        self.assertEqual(diagnostic["nested_data_keys"], ["progress", "status"])

    def test_failed_poll_is_terminal_and_never_downloads(self) -> None:
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        task_id = adapter.submit(self._request())
        transport.response = {
            "status": "failed",
            "error": {"code": "content_policy", "message": "request rejected"},
        }

        result = adapter.poll(task_id)

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "content_policy")
        with self.assertRaises(AdapterFailure) as download:
            adapter.download(task_id)
        self.assertEqual(download.exception.code, "DOWNLOAD_NOT_READY")
        self.assertEqual(transport.download_calls, [])

    def test_cancel_timeout_and_attempt_budget_fail_closed(self) -> None:
        now = [0.0]
        transport = RecordingTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
            clock=lambda: now[0],
        )
        task_id = adapter.submit(self._request())

        with self.assertRaises(AdapterFailure) as cancel:
            adapter.cancel(task_id)
        self.assertEqual(cancel.exception.code, "CANCEL_NOT_SUPPORTED")

        no_credential = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(environ={}),
        )
        with self.assertRaises(AdapterFailure) as unsupported:
            no_credential.cancel(task_id)
        self.assertEqual(unsupported.exception.code, "CANCEL_NOT_SUPPORTED")

        now[0] = 601.0
        with self.assertRaises(AdapterFailure) as timeout:
            adapter.poll(task_id)
        self.assertEqual(timeout.exception.code, "TIMEOUT")
        self.assertEqual(len(transport.calls), 1)

        with self.assertRaises(AdapterFailure) as exhausted:
            adapter.submit(self._request())
        self.assertEqual(exhausted.exception.code, "PROVIDER_FORBIDDEN")
        self.assertEqual(len(transport.calls), 1)

    def test_late_completed_artifact_is_recorded_but_not_downloaded(self) -> None:
        now = [0.0]
        transport = AdvancingTransport(now)
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
            clock=lambda: now[0],
        )
        task_id = adapter.submit(self._request())
        transport.response = {
            "status": "completed",
            "progress": 100,
            "metadata": {"url": "https://download.example/signed-video.mp4"},
        }

        with self.assertRaises(AdapterFailure) as timeout:
            adapter.poll(task_id)
        self.assertEqual(timeout.exception.code, "TIMEOUT")
        with self.assertRaises(AdapterFailure) as late:
            adapter.download(task_id)
        self.assertEqual(late.exception.code, "LATE_ARTIFACT")
        self.assertEqual(transport.download_calls, [])

    def test_source_has_no_cross_skill_private_import(self) -> None:
        source_path = SOURCE_ROOT / "ai_video_platform" / "skills" / "video_generation" / "seedance_nz_adapter.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("skills.", node.module)
            if isinstance(node, ast.Import):
                self.assertTrue(all("ai_video_platform.skills." not in item.name for item in node.names))

    def test_submit_image_uses_fixed_endpoint_model_and_metadata(self) -> None:
        transport = RecordingTransport()
        transport.response = {"id": "task-image-12345678", "status": "queued"}
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )

        job_id = adapter.submit_image({
            "prompt": "High-end skincare product",
            "model": "must-not-override",
            "metadata": {"resolution": "must-not-override"},
        })

        self.assertEqual(job_id, "task-image-12345678")
        self.assertEqual(
            transport.calls[0],
            {
                "method": "POST",
                "path": "/v1/image/generations",
                "credential": "sk-test-key",
                "payload": {
                    "model": "seedream-v5-pro-t2i",
                    "prompt": "High-end skincare product",
                    "metadata": {"resolution": "1k", "output_format": "jpeg"},
                },
            },
        )

    def test_submit_image_to_image_uses_fixed_model_and_one_to_ten_references(self) -> None:
        transport = RecordingTransport()
        transport.response = {"id": "task-image-12345678", "status": "queued"}
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
            remaining_attempts=2,
        )
        images = ["https://assets.example/reference-1.jpeg", "https://assets.example/reference-2.jpeg"]

        adapter.submit_image({"prompt": "Match the approved product", "images": images})

        self.assertEqual(transport.calls[0]["payload"]["model"], "seedream-v5-pro-i2i")
        self.assertEqual(transport.calls[0]["payload"]["images"], images)
        with self.assertRaises(AdapterFailure) as too_many:
            adapter.submit_image({
                "prompt": "Match the approved product",
                "images": [f"https://assets.example/reference-{index}.jpeg" for index in range(11)],
            })
        self.assertEqual(too_many.exception.code, "REQUEST_INVALID")
        self.assertEqual(len(transport.calls), 1)

    def test_poll_image_success_downloads_signed_url_and_supports_nested_fallback(self) -> None:
        transport = RecordingTransport()
        transport.response = {"id": "task-image-12345678", "status": "queued"}
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )
        job_id = adapter.submit_image({"prompt": "High-end skincare product"})
        transport.response = {
            "code": "success",
            "data": {
                "task_id": job_id,
                "status": "SUCCESS",
                "data": {"content": {"image_url": "https://download.example/signed-image.jpeg"}},
            },
        }

        completed = adapter.poll_image(job_id)
        artifact = adapter.download_image(job_id)

        self.assertEqual(completed["data"]["result_url"], "https://download.example/signed-image.jpeg")
        self.assertEqual(artifact["bytes"], b"production-video")
        self.assertEqual(artifact["content_type"], "image/jpeg")
        self.assertEqual(
            artifact["sha256"],
            "sha256:" + hashlib.sha256(b"production-video").hexdigest(),
        )
        self.assertEqual(transport.download_calls, ["https://download.example/signed-image.jpeg"])

    def test_image_unauthorized_and_failure_paths_are_fail_closed(self) -> None:
        credential = "sk-test-key"
        transport = RecordingTransport()
        transport.failure = AdapterFailure(
            "PROVIDER_FORBIDDEN",
            "Seedance.nz rejected " + credential,
            retryable=False,
            http_status=401,
            provider_error_summary={"authorization": credential},
        )
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": credential},
            ),
            remaining_attempts=2,
        )

        with self.assertRaises(AdapterFailure) as unauthorized:
            adapter.submit_image({"prompt": "High-end skincare product"})
        self.assertEqual(unauthorized.exception.code, "PROVIDER_FORBIDDEN")
        self.assertFalse(unauthorized.exception.retryable)
        self.assertNotIn(credential, str(unauthorized.exception.provider_error_summary))

        transport.failure = None
        transport.response = {"id": "task-image-12345678", "status": "queued"}
        job_id = adapter.submit_image({"prompt": "High-end skincare product"})
        transport.response = {
            "code": "success",
            "data": {
                "task_id": job_id,
                "status": "FAILURE",
                "error": {"code": "content_policy", "message": "request rejected"},
            },
        }

        result = adapter.poll_image(job_id)

        self.assertEqual(result["data"]["status"], "FAILURE")
        with self.assertRaises(AdapterFailure) as not_ready:
            adapter.download_image(job_id)
        self.assertEqual(not_ready.exception.code, "DOWNLOAD_NOT_READY")
        self.assertEqual(transport.download_calls, [])


class SeedanceNzUploaderTests(unittest.TestCase):
    def test_production_and_fake_uploaders_return_valid_metadata(self) -> None:
        transport = RecordingTransport()
        uploader = SeedanceNzFileUploader(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": "sk-test-key"},
            ),
        )

        result = uploader.upload(
            file_name="reference.png",
            file_bytes=b"png",
            media_type="image/png",
        )

        self.assertEqual(
            result,
            {
                "url": "https://files.example/reference.png",
                "file_type": "image",
                "size": 3,
                "expires_in": 86400,
            },
        )
        self.assertEqual(transport.upload_calls[0]["file_name"], "reference.png")
        self.assertEqual(uploader.network_calls, 1)

        fake = FakeSeedanceNzFileUploader()
        first = fake.upload(file_name="reference.png", file_bytes=b"png", media_type="image/png")
        second = fake.upload(file_name="reference.png", file_bytes=b"png", media_type="image/png")
        self.assertEqual(first, second)
        self.assertEqual(first["file_type"], "image")
        self.assertEqual(first["size"], 3)
        self.assertEqual(first["expires_in"], 86400)
        self.assertEqual(fake.network_calls, 0)

    def test_upload_rate_limit_is_non_retryable_and_redacted(self) -> None:
        credential = "sk-test-key"
        transport = RecordingTransport()
        transport.upload_failure = AdapterFailure(
            "rate_limited",
            "upload rejected " + credential,
            retryable=True,
            http_status=429,
            provider_error_summary=credential,
        )
        uploader = SeedanceNzFileUploader(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(
                environ={"SEEDANCE_NZ_API_KEY": credential},
            ),
        )

        with self.assertRaises(AdapterFailure) as captured:
            uploader.upload(file_name="reference.png", file_bytes=b"png", media_type="image/png")

        self.assertEqual(captured.exception.code, "rate_limited")
        self.assertFalse(captured.exception.retryable)
        self.assertEqual(captured.exception.http_status, 429)
        self.assertNotIn(credential, str(captured.exception))
        self.assertNotIn(credential, str(captured.exception.provider_error_summary))


class SeedanceNzHttpTransportTests(unittest.TestCase):
    def test_transport_builds_json_upload_and_credential_free_download_requests(self) -> None:
        opener = RecordingOpener([
            FakeHttpResponse(json.dumps({"task_id": "task-12345678"}).encode("utf-8")),
            FakeHttpResponse(json.dumps({
                "url": "https://files.example/reference.png",
                "file_type": "image",
                "size": 3,
                "expires_in": 86400,
            }).encode("utf-8")),
            FakeHttpResponse(b"video"),
        ])
        transport = UrllibSeedanceNzHttpTransport(opener=opener)

        response = transport.request_json(
            "POST",
            "/v1/videos",
            "sk-test-key",
            payload={"model": MODEL_ID},
        )
        upload = transport.upload_multipart(
            "sk-test-key",
            file_name="reference.png",
            file_bytes=b"png",
            media_type="image/png",
        )
        content = transport.download("https://download.example/video.mp4?signature=opaque")

        self.assertEqual(response, {"task_id": "task-12345678"})
        self.assertEqual(upload["expires_in"], 86400)
        self.assertEqual(content, b"video")
        json_request = opener.calls[0]["request"]
        self.assertEqual(json_request.full_url, "https://api.seedance.nz/v1/videos")
        self.assertEqual(json_request.get_method(), "POST")
        self.assertEqual(json_request.get_header("Authorization"), "Bearer sk-test-key")
        self.assertEqual(json_request.get_header("Content-type"), "application/json")
        upload_request = opener.calls[1]["request"]
        self.assertEqual(upload_request.full_url, "https://api.seedance.nz/v1/files/upload")
        self.assertIn(b'name="file"', upload_request.data)
        self.assertIn(b'filename="reference.png"', upload_request.data)
        download_request = opener.calls[2]["request"]
        self.assertIsNone(download_request.get_header("Authorization"))

    def test_transport_maps_rate_limit_without_leaking_credential(self) -> None:
        credential = "sk-test-key"
        error = HTTPError(
            "https://api.seedance.nz/v1/files/upload",
            429,
            "rate limited",
            hdrs=None,
            fp=BytesIO(json.dumps({"error": {"message": credential}}).encode("utf-8")),
        )
        transport = UrllibSeedanceNzHttpTransport(opener=RecordingOpener([error]))

        with self.assertRaises(AdapterFailure) as captured:
            transport.upload_multipart(
                credential,
                file_name="reference.png",
                file_bytes=b"png",
                media_type="image/png",
            )

        self.assertEqual(captured.exception.code, "rate_limited")
        self.assertFalse(captured.exception.retryable)
        self.assertEqual(captured.exception.http_status, 429)
        self.assertNotIn(credential, str(captured.exception.provider_error_summary))


if __name__ == "__main__":
    unittest.main()
