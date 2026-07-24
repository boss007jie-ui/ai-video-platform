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
    KieReferenceImageUploader,
    KieVideoProviderAdapter,
    VideoGenerationInterface,
)
from ai_video_platform.skills.video_generation.adapters import AdapterFailure
from ai_video_platform.skills.video_generation.kie_adapter import BROWSER_HEADERS, UrllibKieHttpTransport
from ai_video_platform.skills.video_generation.kie_smoke import build_smoke_request, run_smoke, validate_reference_digests
from ai_video_platform.skills.video_generation.ledger import InMemoryVideoExecutionLedger
from tests.skills.video_generation.test_video_generation_interface import digest, generation_request


NOW = datetime(2026, 7, 21, 4, 0, tzinfo=timezone.utc)


class RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.downloads: list[str] = []
        self.http_status_chain: list[int] = []
        completed_response: dict[str, object] = {
            "code": 200,
            "msg": "success",
            "data": {
                "taskId": "task_bytedance_safe_001",
                "model": "bytedance/seedance-2-fast",
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
        }
        self.poll_responses: list[dict[str, object]] = [
            completed_response,
            {**completed_response, "data": dict(completed_response["data"])},
            {**completed_response, "data": dict(completed_response["data"])},
        ]

    def request_json(
        self,
        method: str,
        path: str,
        api_key: str,
        *,
        payload: dict[str, object] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.http_status_chain.append(200)
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
        self.http_status_chain.append(200)
        self.downloads.append(uri)
        self.requests.append({"method": "DOWNLOAD"})
        return b"synthetic-kie-video"

    def upload_multipart(
        self,
        credential: str,
        *,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
        upload_path: str,
    ) -> dict[str, object]:
        self.http_status_chain.append(200)
        self.requests.append({
            "method": "UPLOAD",
            "api_key_present": bool(credential),
            "file_bytes": file_bytes,
            "media_type": media_type,
            "upload_path": upload_path,
            "file_name": file_name,
        })
        return {
            "code": 200,
            "msg": "success",
            "data": {
                "downloadUrl": "https://tempfile.redpandaai.co/ftg-p-video-001/reference.jpg",
            },
        }


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
        "model_id": "bytedance/seedance-2-fast",
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
    @staticmethod
    def _with_reference_assets(package, assets):
        role_map = package["reference_role_mapping"]
        role_map["references"] = [
            {
                "asset_ref": item["uri"],
                "sha256": item["sha256"],
                "role": item["role"],
                "provider_execution_input": True,
                "first_frame_eligible": False,
            }
            for item in assets
        ]
        role_map["artifact_digest"] = digest({key: value for key, value in role_map.items() if key != "artifact_digest"})
        master = package["video_generation_storyboard_master"]
        master["reference_role_mapping_ref"] = role_map["artifact_digest"]
        master["artifact_digest"] = digest({key: value for key, value in master.items() if key != "artifact_digest"})
        production_panels = [item for item in package["asset_mapping"] if item.get("role") == "production_panel"]
        package["asset_mapping"] = production_panels + [
            {
                "role": item["role"],
                "asset_id": item["asset_id"],
                "uri": item["uri"],
                "sha256": item["sha256"],
                "approval_state": "approved",
                "provider_execution_input": True,
            }
            for item in assets
        ]
        package["artifact_digest"] = digest({key: value for key, value in package.items() if key != "artifact_digest"})
        return package

    def test_smoke_request_is_fixed_to_revision_d_envelope(self) -> None:
        package = generation_request()["execution_package"]
        digest = package["asset_mapping"][0]["sha256"]
        self._with_reference_assets(package, [{"role": "product_reference", "asset_id": "asset-002", "uri": "memory://detail.png", "sha256": "sha256:" + "4" * 64}])
        validate_reference_digests(package, [digest, "sha256:" + "4" * 64])
        request = build_smoke_request(
            package,
            ["https://assets.example.test/one.jpg", "https://assets.example.test/two.jpg"],
            now=NOW,
        )

        self.assertEqual(request["budget"], {
            "estimated_cost_units": 100,
            "max_cost_units": 100,
            "max_requests": 1,
            "max_concurrency": 1,
            "max_attempts": 2,
            "timeout_seconds": 1800,
        })
        self.assertEqual(request["output"]["duration"], 5)
        self.assertEqual(request["output"]["resolution"], "480p")
        self.assertEqual(request["provider_binding"]["model_id"], "bytedance/seedance-2-fast")
        self.assertEqual(request["approval_record"]["approval_id"], "ftg-p-video-002-revision-d")
        self.assertEqual(request["approval_record"]["decision_ref"], "FTG-P-VIDEO-002-REVISION-D")
        self.assertEqual(request["provider_binding"]["binding_ref"], "ftg-p-video-002-revision-d")
        self.assertEqual(request["idempotency_key"], "ftg-p-video-002-revision-d-20260722")
        self.assertFalse(request["output"]["generate_audio"])
        self.assertFalse(request["output"]["web_search"])

    def test_revision_d_success_receipt_keeps_task_id_and_download_observability(self) -> None:
        import hashlib
        import json
        import tempfile

        task_id = "c" * 32
        credential = "d" * 32

        class HexTaskTransport(RecordingTransport):
            def __init__(self) -> None:
                super().__init__()
                for response in self.poll_responses:
                    response["data"]["taskId"] = task_id

            def request_json(self, method, path, api_key, *, payload=None, query=None):
                if method == "POST":
                    self.http_status_chain.append(200)
                    self.requests.append({
                        "method": method,
                        "path": path,
                        "api_key_present": bool(api_key),
                        "payload": payload,
                        "query": query,
                    })
                    return {"code": 200, "msg": "success", "data": {"taskId": task_id}}
                return super().request_json(method, path, api_key, payload=payload, query=query)

        package = generation_request()["execution_package"]
        first_content = b"revision-d-reference-one"
        second_content = b"revision-d-reference-two"
        first_digest = "sha256:" + hashlib.sha256(first_content).hexdigest()
        second_digest = "sha256:" + hashlib.sha256(second_content).hexdigest()
        asset_mapping = [
            {
                "role": "product_reference",
                "asset_id": "asset-001",
                "uri": "memory://one.jpg",
                "sha256": first_digest,
            },
            {
                "role": "style_reference",
                "asset_id": "asset-002",
                "uri": "memory://two.jpg",
                "sha256": second_digest,
            },
        ]
        self._with_reference_assets(package, asset_mapping)
        transport = HexTaskTransport()
        resolver = KieCredentialResolver(environ={"KIE_API_KEY": credential})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = root / "package.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            first_path = root / "one.jpg"
            second_path = root / "two.jpg"
            first_path.write_bytes(first_content)
            second_path.write_bytes(second_content)
            evidence_dir = root / "evidence"
            with (
                patch("ai_video_platform.skills.video_generation.kie_smoke.UrllibKieHttpTransport", return_value=transport),
                patch("ai_video_platform.skills.video_generation.kie_smoke.KieCredentialResolver", return_value=resolver),
                patch(
                    "ai_video_platform.skills.video_generation.kie_smoke._default_reservation_path",
                    return_value=root / "revision-d-reservation.json",
                ),
            ):
                receipt = run_smoke(
                    package_path=package_path,
                    reference_paths=[first_path, second_path],
                    reference_sha256=[first_digest, second_digest],
                    evidence_dir=evidence_dir,
                    poll_interval_seconds=0,
                )

                persisted = json.loads((evidence_dir / "provider-result.json").read_text(encoding="utf-8"))

                post_count = sum(item.get("method") == "POST" for item in transport.requests)
                with self.assertRaises(FileExistsError):
                    run_smoke(
                        package_path=package_path,
                        reference_paths=[first_path, second_path],
                        reference_sha256=[first_digest, second_digest],
                        evidence_dir=root / "different-evidence-directory",
                        poll_interval_seconds=0,
                    )
                self.assertEqual(sum(item.get("method") == "POST" for item in transport.requests), post_count)

        self.assertEqual(receipt["revision"], "D")
        self.assertEqual(receipt["task_id"], task_id)
        self.assertEqual(receipt["generation_submissions"], 1)
        self.assertEqual(receipt["http_status"], 200)
        self.assertEqual(receipt["http_status_chain"], [200, 200, 200, 200, 200, 200])
        self.assertEqual(receipt["download_http_status_chain"], [200, 200])
        self.assertEqual(receipt["download_attempts"], [{
            "attempt": 1,
            "refresh_http_status": 200,
            "download_http_status": 200,
            "outcome": "success",
            "retry_reason": None,
        }])
        self.assertEqual(
            receipt["download_http_status_chain_provenance"],
            "CAPTURED_BY_REVISION_D_CONTROLLER",
        )
        self.assertEqual(receipt["secret_scan_matches"], 0)
        self.assertEqual(receipt["secret_scan_status"], "PASS")
        self.assertEqual(persisted, receipt)
        self.assertNotIn(credential, json.dumps(receipt))

    def test_reference_uploader_verifies_local_digest_and_returns_safe_https_url(self) -> None:
        import hashlib
        import tempfile

        content = b"synthetic-approved-reference"
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        transport = RecordingTransport()
        uploader = KieReferenceImageUploader(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "approved-reference.jpg"
            image.write_bytes(content)
            uri = uploader.upload(image, expected_sha256=expected)

        self.assertEqual(uri, "https://tempfile.redpandaai.co/ftg-p-video-001/reference.jpg")
        sent = transport.requests[0]
        self.assertEqual(sent["method"], "UPLOAD")
        self.assertEqual(sent["upload_path"], "ftg-p-video-001")
        self.assertEqual(sent["file_bytes"], content)
        self.assertEqual(sent["media_type"], "image/jpeg")
        self.assertNotIn("synthetic-value", str(sent))

    def test_reference_upload_uses_stream_multipart_browser_headers_and_fallback_path(self) -> None:
        import hashlib
        import tempfile

        class MultipartTransport(RecordingTransport):
            def upload_multipart(self, credential, *, file_name, file_bytes, media_type, upload_path):
                self.requests.append({
                    "method": "UPLOAD",
                    "api_key_present": bool(credential),
                    "file_name": file_name,
                    "file_bytes": file_bytes,
                    "media_type": media_type,
                    "upload_path": upload_path,
                })
                return {"code": 200, "data": {"filePath": "smoke/ref.jpg"}}

        content = b"multipart-reference"
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        transport = MultipartTransport()
        uploader = KieReferenceImageUploader(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "approved-reference.jpg"
            image.write_bytes(content)
            uri = uploader.upload(image, expected_sha256=expected)

        self.assertEqual(uri, "https://tempfile.redpandaai.co/smoke/ref.jpg")
        self.assertEqual(transport.requests[0]["file_bytes"], content)
        self.assertEqual(transport.requests[0]["upload_path"], "ftg-p-video-001")
        self.assertEqual(transport.requests[0]["media_type"], "image/jpeg")
        self.assertEqual(BROWSER_HEADERS["Accept-Encoding"], "identity")
        self.assertIn("Chrome/126.0.0.0", BROWSER_HEADERS["User-Agent"])

    def test_reference_upload_falls_back_from_invalid_preferred_urls(self) -> None:
        import hashlib
        import tempfile

        class FallbackTransport(RecordingTransport):
            def upload_multipart(self, *args, **kwargs):
                return {
                    "code": 200,
                    "data": {
                        "downloadUrl": "",
                        "fileUrl": "ftp://unsafe.example.test/reference.jpg",
                        "filePath": "/smoke/safe-reference.jpg",
                    },
                }

        content = b"fallback-reference"
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        uploader = KieReferenceImageUploader(
            transport=FallbackTransport(),
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "approved-reference.jpg"
            image.write_bytes(content)
            uri = uploader.upload(image, expected_sha256=expected)

        self.assertEqual(uri, "https://tempfile.redpandaai.co/smoke/safe-reference.jpg")

    def test_upload_failure_preserves_http_status_and_provider_summary(self) -> None:
        class FailingTransport(RecordingTransport):
            def upload_multipart(self, *args, **kwargs):
                raise AdapterFailure(
                    "KIE_UPLOAD_ERROR",
                    "KIE reference upload failed",
                    retryable=False,
                    http_status=1010,
                    provider_error_summary="Cloudflare browser_signature_banned",
                )

        import hashlib
        import tempfile

        content = b"diagnostic-reference"
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        uploader = KieReferenceImageUploader(
            transport=FailingTransport(),
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "approved-reference.jpg"
            image.write_bytes(content)
            with self.assertRaises(AdapterFailure) as captured:
                uploader.upload(image, expected_sha256=expected)
        self.assertEqual(captured.exception.http_status, 1010)
        self.assertEqual(captured.exception.provider_error_summary, "Cloudflare browser_signature_banned")

    def test_upload_business_failure_preserves_redacted_provider_summary(self) -> None:
        class BusinessFailureTransport(RecordingTransport):
            def upload_multipart(self, *args, **kwargs):
                return {
                    "code": 422,
                    "message": "unsupported file",
                    "data": {"apiKey": "synthetic-secret"},
                }

        import hashlib
        import tempfile

        content = b"business-failure-reference"
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        uploader = KieReferenceImageUploader(
            transport=BusinessFailureTransport(),
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "approved-reference.jpg"
            image.write_bytes(content)
            with self.assertRaises(AdapterFailure) as captured:
                uploader.upload(image, expected_sha256=expected)

        self.assertEqual(captured.exception.http_status, 200)
        self.assertIn("unsupported file", captured.exception.provider_error_summary)
        self.assertNotIn("synthetic-secret", captured.exception.provider_error_summary)

    def test_upload_invalid_url_preserves_provider_response_diagnostics(self) -> None:
        import hashlib
        import tempfile

        class InvalidUrlTransport(RecordingTransport):
            def upload_multipart(self, *args, **kwargs):
                return {"code": 200, "message": "stored without URL", "data": {}}

        content = b"invalid-url-reference"
        expected = "sha256:" + hashlib.sha256(content).hexdigest()
        uploader = KieReferenceImageUploader(
            transport=InvalidUrlTransport(),
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "approved-reference.jpg"
            image.write_bytes(content)
            with self.assertRaises(AdapterFailure) as captured:
                uploader.upload(image, expected_sha256=expected)

        self.assertEqual(captured.exception.http_status, 200)
        self.assertIn("stored without URL", captured.exception.provider_error_summary)
        self.assertNotIn("synthetic-value", str(captured.exception))

    def test_revision_d_failure_receipt_records_http_status_and_redacts_credential(self) -> None:
        import json
        import tempfile

        package = generation_request()["execution_package"]
        first_digest = package["asset_mapping"][0]["sha256"]
        second_digest = "sha256:" + "4" * 64
        package["asset_mapping"].append({
            "shot_id": "shot-001",
            "role": "detail",
            "asset_id": "asset-002",
            "uri": "memory://detail.png",
            "sha256": second_digest,
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = root / "package.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            evidence_dir = root / "evidence"
            credential = "e" * 32
            resolver = KieCredentialResolver(environ={"KIE_API_KEY": credential})
            with (
                patch.object(
                    KieReferenceImageUploader,
                    "upload",
                    side_effect=AdapterFailure(
                        "KIE_UPLOAD_ERROR",
                        "KIE reference upload failed",
                        retryable=False,
                        http_status=403,
                        provider_error_summary="Cloudflare request denied " + credential,
                    ),
                ),
                patch("ai_video_platform.skills.video_generation.kie_smoke.KieCredentialResolver", return_value=resolver),
                patch(
                    "ai_video_platform.skills.video_generation.kie_smoke._default_reservation_path",
                    return_value=root / "revision-d-reservation.json",
                ),
            ):
                with self.assertRaises(AdapterFailure):
                    run_smoke(
                        package_path=package_path,
                        reference_paths=[root / "one.jpg", root / "two.jpg"],
                        reference_sha256=[first_digest, second_digest],
                        evidence_dir=evidence_dir,
                        poll_interval_seconds=0,
                    )
            receipt = json.loads((evidence_dir / "provider-result.json").read_text(encoding="utf-8"))

        self.assertEqual(receipt["http_status"], 403)
        self.assertEqual(receipt["provider_error_summary"], "Cloudflare request denied [REDACTED]")
        self.assertEqual(receipt["secret_scan_failure_code"], "CREDENTIAL_MATERIAL_DETECTED")
        self.assertEqual(receipt["generation_submissions"], 0)
        self.assertEqual(receipt["ledger_state_chain"], [])
        self.assertIsNone(receipt["credits_consumed"])
        self.assertIsNone(receipt["artifact_uri"])
        self.assertIsNone(receipt["size_bytes"])
        self.assertIsNone(receipt["sha256"])
        self.assertEqual(receipt["http_status_chain"], [])
        self.assertEqual(receipt["secret_scan_status"], "PASS")
        self.assertEqual(receipt["secret_scan_matches"], 0)
        self.assertNotIn(credential, json.dumps(receipt))

    def test_revision_d_missing_credential_does_not_consume_reservation(self) -> None:
        import json
        import tempfile

        package = generation_request()["execution_package"]
        first_digest = package["asset_mapping"][0]["sha256"]
        second_digest = "sha256:" + "4" * 64
        package["asset_mapping"].append({
            "shot_id": "shot-001",
            "role": "detail",
            "asset_id": "asset-002",
            "uri": "memory://detail.png",
            "sha256": second_digest,
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = root / "package.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            reservation = root / "revision-d-reservation.json"
            with (
                patch(
                    "ai_video_platform.skills.video_generation.kie_smoke.KieCredentialResolver",
                    return_value=KieCredentialResolver(environ={}),
                ),
                patch(
                    "ai_video_platform.skills.video_generation.kie_smoke._default_reservation_path",
                    return_value=reservation,
                ),
            ):
                with self.assertRaises(AdapterFailure) as captured:
                    run_smoke(
                        package_path=package_path,
                        reference_paths=[root / "one.jpg", root / "two.jpg"],
                        reference_sha256=[first_digest, second_digest],
                        evidence_dir=root / "evidence",
                        poll_interval_seconds=0,
                    )

            self.assertEqual(captured.exception.code, "CREDENTIAL_UNAVAILABLE")
            self.assertFalse(reservation.exists())
            self.assertFalse((root / "evidence" / "provider-attempt.json").exists())

    def test_revision_d_download_403_exhaustion_receipt_keeps_cost_and_observability(self) -> None:
        import hashlib
        import json
        import tempfile

        class Download403Transport(RecordingTransport):
            def download(self, uri: str) -> bytes:
                del uri
                self.http_status_chain.append(403)
                raise AdapterFailure(
                    "KIE_DOWNLOAD_ERROR",
                    "KIE artifact download failed",
                    retryable=False,
                    http_status=403,
                    provider_error_summary="Cloudflare access denied",
                )

        first_content = b"download-failure-reference-one"
        second_content = b"download-failure-reference-two"
        first_digest = "sha256:" + hashlib.sha256(first_content).hexdigest()
        second_digest = "sha256:" + hashlib.sha256(second_content).hexdigest()
        package = generation_request()["execution_package"]
        asset_mapping = [
            {"role": "product_reference", "asset_id": "asset-001", "uri": "memory://one.jpg", "sha256": first_digest},
            {"role": "style_reference", "asset_id": "asset-002", "uri": "memory://two.jpg", "sha256": second_digest},
        ]
        self._with_reference_assets(package, asset_mapping)

        transport = Download403Transport()
        resolver = KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = root / "package.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            first_path = root / "one.jpg"
            second_path = root / "two.jpg"
            first_path.write_bytes(first_content)
            second_path.write_bytes(second_content)
            evidence_dir = root / "evidence"
            with (
                patch("ai_video_platform.skills.video_generation.kie_smoke.UrllibKieHttpTransport", return_value=transport),
                patch("ai_video_platform.skills.video_generation.kie_smoke.KieCredentialResolver", return_value=resolver),
                patch(
                    "ai_video_platform.skills.video_generation.kie_smoke._default_reservation_path",
                    return_value=root / "revision-d-reservation.json",
                ),
            ):
                with self.assertRaises(Exception):
                    run_smoke(
                        package_path=package_path,
                        reference_paths=[first_path, second_path],
                        reference_sha256=[first_digest, second_digest],
                        evidence_dir=evidence_dir,
                        poll_interval_seconds=0,
                    )
            receipt = json.loads((evidence_dir / "provider-result.json").read_text(encoding="utf-8"))

        self.assertEqual(receipt["task_id"], "task_bytedance_safe_001")
        self.assertEqual(receipt["generation_submissions"], 1)
        self.assertEqual(receipt["credits_consumed"], 3)
        self.assertEqual(receipt["ledger_state_chain"][-1], "succeeded")
        self.assertEqual(receipt["http_status"], 403)
        self.assertEqual(receipt["http_status_chain"], [200, 200, 200, 200, 200, 403, 200, 403])
        self.assertEqual(receipt["download_http_status_chain"], [200, 403, 200, 403])
        self.assertEqual(len(receipt["download_attempts"]), 2)
        self.assertEqual(receipt["download_attempts"][0]["retry_reason"], "HTTP_403_REFRESH_RESULT_URL")
        self.assertEqual(
            receipt["download_attempts"][1]["retry_reason"],
            "EXHAUSTED_HTTP_403_REFRESH_RESULT_URL",
        )
        self.assertEqual(
            receipt["download_http_status_chain_provenance"],
            "CAPTURED_BY_REVISION_D_CONTROLLER",
        )
        self.assertIsNone(receipt["artifact_uri"])
        self.assertIsNone(receipt["size_bytes"])
        self.assertIsNone(receipt["sha256"])
        self.assertFalse(receipt["late_artifact_download_performed"])

    def test_reference_uploader_rejects_tampering_and_oversize_before_http(self) -> None:
        import hashlib
        import tempfile

        transport = RecordingTransport()
        uploader = KieReferenceImageUploader(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "approved-reference.jpg"
            image.write_bytes(b"changed")
            with self.assertRaises(AdapterFailure):
                uploader.upload(image, expected_sha256="sha256:" + hashlib.sha256(b"approved").hexdigest())
            image.write_bytes(b"x" * (1024 * 1024 + 1))
            with self.assertRaises(AdapterFailure):
                uploader.upload(image, expected_sha256="sha256:" + hashlib.sha256(image.read_bytes()).hexdigest())

        self.assertEqual(transport.requests, [])

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

    def test_default_http_transport_builds_exact_stream_upload_request(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"code":200,"data":{"downloadUrl":"https://tempfile.redpandaai.co/ref.jpg"}}'

        with patch("ai_video_platform.skills.video_generation.kie_adapter.build_opener") as build:
            build.return_value.open.return_value = Response()
            transport = UrllibKieHttpTransport()
            transport.upload_multipart(
                "synthetic-value",
                file_name="reference.jpg",
                file_bytes=b"image-bytes",
                media_type="image/jpeg",
                upload_path="ftg-p-video-001",
            )

        upload_request = build.return_value.open.call_args.args[0]
        body = upload_request.data
        self.assertEqual(upload_request.full_url, "https://kieai.redpandaai.co/api/file-stream-upload")
        self.assertEqual(upload_request.method, "POST")
        self.assertEqual(upload_request.get_header("Origin"), "https://kieai.redpandaai.co")
        self.assertEqual(upload_request.get_header("Accept-encoding"), "identity")
        self.assertIn("Chrome/126.0.0.0", upload_request.get_header("User-agent"))
        self.assertTrue(upload_request.get_header("Content-type").startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="file"; filename="reference.jpg"', body)
        self.assertIn(b'name="uploadPath"', body)
        self.assertIn(b"ftg-p-video-001", body)
        self.assertIn(b'name="fileName"', body)
        self.assertNotIn(b"synthetic-value", body)

    def test_http_error_summary_recursively_redacts_provider_credentials(self) -> None:
        from io import BytesIO
        from urllib.error import HTTPError

        leaked_hex = "a" * 32
        body = (
            '{"message":"credential ' + leaked_hex + '",'
            '"private_key":"provider-private-value","stack":"provider-stack"}'
        ).encode("utf-8")
        error = HTTPError(
            "https://kieai.redpandaai.co/api/file-stream-upload",
            403,
            "Forbidden",
            {},
            BytesIO(body),
        )
        self.addCleanup(error.close)
        with patch("ai_video_platform.skills.video_generation.kie_adapter.build_opener") as build:
            build.return_value.open.side_effect = error
            transport = UrllibKieHttpTransport()
            with self.assertRaises(AdapterFailure) as captured:
                transport.upload_multipart(
                    leaked_hex,
                    file_name="reference.jpg",
                    file_bytes=b"image-bytes",
                    media_type="image/jpeg",
                    upload_path="ftg-p-video-001",
                )

        summary = captured.exception.provider_error_summary
        self.assertEqual(captured.exception.http_status, 403)
        self.assertNotIn(leaked_hex, summary)
        self.assertNotIn("provider-private-value", summary)
        self.assertNotIn("provider-stack", summary)
        self.assertIn("[REDACTED]", summary)

    def test_thirty_two_hex_task_id_is_allowed_unless_it_matches_the_credential(self) -> None:
        class HexTaskTransport(RecordingTransport):
            def __init__(self, task_id: str) -> None:
                super().__init__()
                self.task_id = task_id

            def request_json(self, method, path, api_key, *, payload=None, query=None):
                if method == "POST":
                    return {"code": 200, "data": {"taskId": self.task_id}}
                return super().request_json(method, path, api_key, payload=payload, query=query)

        task_id = "c" * 32
        credential = "d" * 32
        adapter = KieVideoProviderAdapter(
            transport=HexTaskTransport(task_id),
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": credential}),
        )
        inspected = VideoGenerationInterface().inspect_video_request(kie_request(), now=NOW)
        self.assertEqual(adapter.submit(inspected), task_id)

        rejecting = KieVideoProviderAdapter(
            transport=HexTaskTransport(credential),
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": credential}),
        )
        with self.assertRaises(AdapterFailure):
            rejecting.submit(inspected)

        poll_transport = HexTaskTransport(task_id)
        poll_rejecting = KieVideoProviderAdapter(
            transport=poll_transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": credential}),
        )
        with self.assertRaises(AdapterFailure):
            poll_rejecting.poll(credential)
        self.assertEqual(poll_transport.requests, [])

    def test_malformed_json_and_download_http_errors_keep_safe_diagnostics(self) -> None:
        from io import BytesIO
        from urllib.error import HTTPError

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"provider malformed body"

        with patch("ai_video_platform.skills.video_generation.kie_adapter.build_opener") as build:
            build.return_value.open.return_value = Response()
            transport = UrllibKieHttpTransport()
            with self.assertRaises(AdapterFailure) as malformed:
                transport.upload_multipart(
                    "synthetic-value",
                    file_name="reference.jpg",
                    file_bytes=b"image-bytes",
                    media_type="image/jpeg",
                    upload_path="ftg-p-video-001",
                )
        self.assertEqual(malformed.exception.http_status, 200)
        self.assertIn("provider malformed body", malformed.exception.provider_error_summary)

        download_error = HTTPError(
            "https://files.example.test/result.mp4",
            404,
            "Not Found",
            {},
            BytesIO(b'{"message":"artifact expired"}'),
        )
        self.addCleanup(download_error.close)
        with patch("ai_video_platform.skills.video_generation.kie_adapter.urlopen", side_effect=download_error):
            with self.assertRaises(AdapterFailure) as download:
                UrllibKieHttpTransport().download("https://files.example.test/result.mp4")
        self.assertEqual(download.exception.http_status, 404)
        self.assertIn("artifact expired", download.exception.provider_error_summary)

    def test_revision_d_artifact_download_uses_browser_headers_without_credential(self) -> None:
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"synthetic-video"

        with patch("ai_video_platform.skills.video_generation.kie_adapter.urlopen", return_value=Response()) as opened:
            content = UrllibKieHttpTransport().download("https://tempfile.aiquickdraw.com/result.mp4")

        request = opened.call_args.args[0]
        self.assertEqual(content, b"synthetic-video")
        self.assertIn("Chrome/126.0.0.0", request.get_header("User-agent"))
        self.assertEqual(request.get_header("Referer"), "https://kie.ai/")
        self.assertEqual(request.get_header("Accept-encoding"), "identity")
        self.assertEqual(request.get_header("Sec-fetch-site"), "cross-site")
        self.assertIsNone(request.get_header("Authorization"))

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
        self.assertEqual(sent["payload"]["model"], "bytedance/seedance-2-fast")
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

    def test_revision_d_403_refreshes_result_url_and_retries_download_once(self) -> None:
        class RefreshingTransport(RecordingTransport):
            def __init__(self) -> None:
                super().__init__()
                base = dict(self.poll_responses[0]["data"])
                self.poll_responses = [
                    {"code": 200, "msg": "success", "data": {**base, "resultJson": '{"resultUrls":["https://files.example.test/stale.mp4"]}'}},
                    {"code": 200, "msg": "success", "data": {**base, "resultJson": '{"resultUrls":["https://files.example.test/refreshed-one.mp4"]}'}},
                    {"code": 200, "msg": "success", "data": {**base, "resultJson": '{"resultUrls":["https://files.example.test/refreshed-two.mp4"]}'}},
                ]

            def download(self, uri: str) -> bytes:
                self.downloads.append(uri)
                if len(self.downloads) == 1:
                    self.http_status_chain.append(403)
                    raise AdapterFailure(
                        "KIE_DOWNLOAD_ERROR",
                        "KIE artifact download failed",
                        retryable=False,
                        http_status=403,
                        provider_error_summary="Cloudflare access denied",
                    )
                self.http_status_chain.append(200)
                return b"revision-d-video"

        transport = RefreshingTransport()
        adapter = KieVideoProviderAdapter(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        interface = VideoGenerationInterface(adapter=adapter, ledger=InMemoryVideoExecutionLedger())
        submitted = interface.submit_video(kie_request(), now=NOW)
        interface.poll_video(submitted["job_id"], now=NOW)

        downloaded = interface.download_video(submitted["job_id"], now=NOW)

        self.assertEqual(transport.downloads, [
            "https://files.example.test/refreshed-one.mp4",
            "https://files.example.test/refreshed-two.mp4",
        ])
        self.assertEqual(downloaded["asset_manifest_request"]["size_bytes"], len(b"revision-d-video"))
        self.assertEqual(downloaded["download_http_status_chain"], [200, 403, 200, 200])
        self.assertEqual(downloaded["download_attempts"], adapter.download_attempts)
        self.assertEqual(adapter.download_http_status_chain, [200, 403, 200, 200])
        self.assertEqual(adapter.download_attempts, [
            {
                "attempt": 1,
                "refresh_http_status": 200,
                "download_http_status": 403,
                "outcome": "retry",
                "retry_reason": "HTTP_403_REFRESH_RESULT_URL",
            },
            {
                "attempt": 2,
                "refresh_http_status": 200,
                "download_http_status": 200,
                "outcome": "success",
                "retry_reason": None,
            },
        ])

    def test_revision_d_download_retry_exhaustion_preserves_cost_and_returns_observation_receipt(self) -> None:
        class ExhaustedTransport(RecordingTransport):
            def __init__(self) -> None:
                super().__init__()
                base = dict(self.poll_responses[0]["data"])
                self.poll_responses = [
                    {"code": 200, "msg": "success", "data": {**base, "resultJson": '{"resultUrls":["https://files.example.test/original.mp4"]}'}},
                    {"code": 200, "msg": "success", "data": {**base, "resultJson": '{"resultUrls":["https://files.example.test/refreshed-one.mp4"]}'}},
                    {"code": 200, "msg": "success", "data": {**base, "resultJson": '{"resultUrls":["https://files.example.test/refreshed-two.mp4"]}'}},
                ]

            def download(self, uri: str) -> bytes:
                self.downloads.append(uri)
                self.http_status_chain.append(503)
                raise AdapterFailure(
                    "KIE_DOWNLOAD_ERROR",
                    "KIE artifact download failed",
                    retryable=True,
                    http_status=503,
                    provider_error_summary="temporary CDN failure",
                )

        transport = ExhaustedTransport()
        ledger = InMemoryVideoExecutionLedger()
        adapter = KieVideoProviderAdapter(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        interface = VideoGenerationInterface(adapter=adapter, ledger=ledger)
        submitted = interface.submit_video(kie_request(), now=NOW)
        interface.poll_video(submitted["job_id"], now=NOW)

        with self.assertRaises(Exception) as captured:
            interface.download_video(submitted["job_id"], now=NOW)

        record = ledger.get(submitted["job_id"])
        self.assertEqual(record["state"], "succeeded")
        self.assertEqual(record["provider_cost_units"], 3)
        self.assertEqual(captured.exception.details["download_http_status_chain"], [200, 503, 200, 503])
        self.assertEqual(captured.exception.details["download_attempts"][-1], {
            "attempt": 2,
            "refresh_http_status": 200,
            "download_http_status": 503,
            "outcome": "failed",
            "retry_reason": "EXHAUSTED_HTTP_503_REFRESH_RESULT_URL",
        })
        self.assertEqual(transport.downloads, [
            "https://files.example.test/refreshed-one.mp4",
            "https://files.example.test/refreshed-two.mp4",
        ])

    def test_provider_terminal_failure_preserves_safe_diagnostics(self) -> None:
        transport = RecordingTransport()
        transport.poll_responses = [{
            "code": 200,
            "msg": "success",
            "data": {
                "taskId": "task_bytedance_safe_001",
                "model": "bytedance/seedance-2-fast",
                "state": "fail",
                "failCode": "MODEL_REJECTED",
                "failMsg": "model id rejected",
                "apiKey": "b" * 32,
                "creditsConsumed": 0,
            },
        }]
        adapter = KieVideoProviderAdapter(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        interface = VideoGenerationInterface(adapter=adapter, ledger=InMemoryVideoExecutionLedger())
        submitted = interface.submit_video(kie_request(), now=NOW)

        failed = interface.poll_video(submitted["job_id"], now=NOW)

        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["provider_http_status"], 200)
        self.assertIn("model id rejected", failed["provider_error_summary"])
        self.assertNotIn("b" * 32, failed["provider_error_summary"])

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

    def test_polling_anomaly_is_terminal_after_one_get_attempt(self) -> None:
        class AnomalousPollTransport(RecordingTransport):
            def __init__(self) -> None:
                super().__init__()
                self.poll_count = 0

            def request_json(self, method, path, api_key, *, payload=None, query=None):
                if method == "GET":
                    self.poll_count += 1
                    raise AdapterFailure("KIE_NETWORK_ERROR", "Synthetic polling anomaly", retryable=True)
                return super().request_json(method, path, api_key, payload=payload, query=query)

        transport = AnomalousPollTransport()
        adapter = KieVideoProviderAdapter(
            transport=transport,
            credential_resolver=KieCredentialResolver(environ={"KIE_API_KEY": "synthetic-value"}),
        )
        interface = VideoGenerationInterface(adapter=adapter, ledger=InMemoryVideoExecutionLedger())
        submitted = interface.submit_video(kie_request(), now=NOW)

        with self.assertRaises(Exception):
            interface.poll_video(submitted["job_id"], now=NOW)

        self.assertEqual(transport.poll_count, 1)

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
