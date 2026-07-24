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
