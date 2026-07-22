from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
from contextlib import redirect_stdout
import io
import tempfile
import unittest

from ai_video_platform.skills.viral_research_asset_collection.media import (
    DirectMediaDownloadAdapter, MEDIA_DOWNLOAD_AUTHORIZATION_ID, UrllibMediaTransport,
)
from ai_video_platform.skills.viral_research_asset_collection.interface import collect_reference_assets
from ai_video_platform.skills.viral_research_asset_collection.storage import ResearchLibraryAdapter
from ai_video_platform.skills.viral_research_asset_collection.cli import main
from ai_video_platform.skills.viral_research_asset_collection.errors import ErrorCode, SkillError


class Response:
    status = 200
    headers = {"Content-Type": "video/mp4", "Content-Length": "4"}
    def __init__(self): self.done = False
    def read(self, size=-1):
        if self.done: return b""
        self.done = True; return b"test"
    def close(self): pass


class ForbiddenResponse(Response):
    status = 403
    headers = {"Content-Type": "text/plain", "Content-Length": "0"}


class Transport:
    def __init__(self): self.calls = []
    def get(self, url, *, timeout_seconds): self.calls.append((url, timeout_seconds)); return Response()


class ForbiddenTransport(Transport):
    def get(self, url, *, timeout_seconds):
        self.calls.append((url, timeout_seconds))
        return ForbiddenResponse()


class SequenceTransport(Transport):
    def __init__(self, responses):
        super().__init__()
        self.responses = iter(responses)

    def get(self, url, *, timeout_seconds):
        self.calls.append((url, timeout_seconds))
        return next(self.responses)


class MediaDownloadTests(unittest.TestCase):
    def candidate(self):
        return {"source_id": "abc123", "content_digest": "a" * 64,
                "source_url": "https://www.tiktok.com/@public/video/abc123",
                "media_url": "https://v45.tiktokcdn-eu.com/video/test.mp4",
                "rights_status": "UNKNOWN",
                "expires_at": "2026-07-29T02:41:16Z"}

    def adapter(self, root, transport):
        metadata = Path(root) / "metadata"; metadata.mkdir()
        candidate = self.candidate()
        (metadata / "abc123.json").write_text(json.dumps(candidate), encoding="utf-8")
        return DirectMediaDownloadAdapter(Path(root), authorization_id=MEDIA_DOWNLOAD_AUTHORIZATION_ID, transport=transport,
            now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc))

    def test_download_receipt_and_idempotent_replay(self):
        with tempfile.TemporaryDirectory() as d:
            transport = Transport()
            adapter = self.adapter(d, transport)
            first = adapter.download(self.candidate())
            second = adapter.download(self.candidate())
            self.assertEqual(first, second)
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(first["lifecycle_state"], "internal_analysis_only")
            self.assertEqual(first["rights_status"], "UNKNOWN")
            self.assertEqual(Path(first["storage_path"]).read_bytes(), b"test")

    def test_idempotent_replay_rejects_tampered_media_without_new_get(self):
        with tempfile.TemporaryDirectory() as d:
            transport = Transport()
            adapter = self.adapter(d, transport)
            receipt = adapter.download(self.candidate())
            Path(receipt["storage_path"]).write_bytes(b"tampered")
            with self.assertRaises(SkillError) as caught:
                adapter.download(self.candidate())
            self.assertEqual(caught.exception.code, ErrorCode.STORAGE_CONFLICT)
            self.assertEqual(len(transport.calls), 1)

    def test_urllib_transport_reuses_one_no_redirect_session(self):
        from unittest.mock import Mock, patch
        opener = Mock()
        opener.open.side_effect = [Response(), Response()]
        with patch("ai_video_platform.skills.viral_research_asset_collection.media.build_opener", return_value=opener) as factory:
            transport = UrllibMediaTransport(authorization_id=MEDIA_DOWNLOAD_AUTHORIZATION_ID)
            transport.get(self.candidate()["media_url"], timeout_seconds=120)
            transport.get(self.candidate()["media_url"], timeout_seconds=120)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(opener.open.call_count, 2)

    def test_real_network_seams_require_explicit_media_authorization(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SkillError) as adapter_error:
                DirectMediaDownloadAdapter(Path(d), transport=Transport())
            self.assertEqual(adapter_error.exception.code, ErrorCode.DOWNLOAD_FORBIDDEN)
        with self.assertRaises(SkillError) as transport_error:
            UrllibMediaTransport()
        self.assertEqual(transport_error.exception.code, ErrorCode.DOWNLOAD_FORBIDDEN)

    def test_rejects_untrusted_host(self):
        with tempfile.TemporaryDirectory() as d:
            adapter = self.adapter(d, Transport())
            candidate = {**self.candidate(), "media_url": "https://evil.example/video.mp4"}
            with self.assertRaises(SkillError) as caught: adapter.download(candidate)
            self.assertEqual(caught.exception.code, ErrorCode.DOWNLOAD_FORBIDDEN)

    def test_rejects_media_url_or_expiry_not_recorded_on_ledgered_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            transport = Transport()
            adapter = self.adapter(d, transport)
            for candidate in (
                {**self.candidate(), "media_url": "https://v45.tiktokcdn-eu.com/video/other.mp4"},
                {**self.candidate(), "expires_at": "2026-07-28T02:41:16Z"},
            ):
                with self.subTest(candidate=candidate):
                    with self.assertRaises(SkillError) as caught:
                        adapter.download(candidate)
                    self.assertEqual(caught.exception.code, ErrorCode.DOWNLOAD_FORBIDDEN)
            self.assertEqual(transport.calls, [])

    def test_normalized_ledger_without_media_url_accepts_allowlisted_candidate_url(self):
        with tempfile.TemporaryDirectory() as d:
            transport = Transport()
            adapter = self.adapter(d, transport)
            metadata_path = Path(d, "metadata", "abc123.json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            del metadata["media_url"]
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            receipt = adapter.download(self.candidate())
            self.assertEqual(receipt["http_status"], 200)
            self.assertEqual(len(transport.calls), 1)

    def test_failed_get_persists_utf8_receipt_before_raising(self):
        with tempfile.TemporaryDirectory() as d:
            adapter = self.adapter(d, ForbiddenTransport())
            with self.assertRaises(SkillError) as caught:
                adapter.download(self.candidate())
            self.assertEqual(caught.exception.code, ErrorCode.DOWNLOAD_FORBIDDEN)
            receipt_path = Path(d, "downloads", "receipts", "abc123.json")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["candidate_digest"], "a" * 64)
            self.assertEqual(receipt["http_status"], 403)
            self.assertEqual(receipt["bytes"], 0)
            self.assertEqual(receipt["attempts"], 1)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertIsNone(receipt["storage_path"])

    def test_incomplete_idempotent_artifact_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            transport = Transport()
            adapter = self.adapter(d, transport)
            Path(d, "downloads", "abc123.mp4").write_bytes(b"orphan")
            with self.assertRaises(SkillError) as caught:
                adapter.download(self.candidate())
            self.assertEqual(caught.exception.code, ErrorCode.STORAGE_CONFLICT)
            self.assertEqual(transport.calls, [])

    def test_failed_get_records_receipt_and_continues_with_next_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            first = {**self.candidate(), "pii_detected": False, "brand_safety": 1.0}
            second = {
                **first,
                "source_id": "def456",
                "content_digest": "b" * 64,
                "media_url": "https://v45.tiktokcdn-eu.com/video/second.mp4",
            }
            metadata = Path(d, "metadata")
            metadata.mkdir()
            for candidate in (first, second):
                Path(metadata, f"{candidate['source_id']}.json").write_text(json.dumps(candidate), encoding="utf-8")
            transport = SequenceTransport([ForbiddenResponse(), Response()])
            adapter = DirectMediaDownloadAdapter(
                Path(d), authorization_id=MEDIA_DOWNLOAD_AUTHORIZATION_ID, transport=transport,
                now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
            )
            result = collect_reference_assets(
                {
                    "selected_candidates": [first, second],
                    "download_policy": "INTERNAL_ANALYSIS_ONLY",
                    "idempotency_key": "media-continue",
                },
                downloader=adapter,
                storage=ResearchLibraryAdapter(Path(d)),
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )
            self.assertEqual([item.source_id for item in result.items], ["def456"])
            self.assertEqual(adapter.attempt_count, 2)
            self.assertEqual([receipt.get("outcome", "succeeded") for receipt in adapter.receipts], ["failed", "succeeded"])

    def test_expired_candidate_records_zero_get_failure_and_continues(self):
        with tempfile.TemporaryDirectory() as d:
            first = {
                **self.candidate(), "expires_at": "2026-07-21T00:00:00Z",
                "pii_detected": False, "brand_safety": 1.0,
            }
            second = {
                **self.candidate(), "source_id": "def456", "content_digest": "b" * 64,
                "media_url": "https://v45.tiktokcdn-eu.com/video/second.mp4",
                "pii_detected": False, "brand_safety": 1.0,
            }
            metadata = Path(d, "metadata")
            metadata.mkdir()
            for candidate in (first, second):
                Path(metadata, f"{candidate['source_id']}.json").write_text(json.dumps(candidate), encoding="utf-8")
            transport = Transport()
            adapter = DirectMediaDownloadAdapter(
                Path(d), authorization_id=MEDIA_DOWNLOAD_AUTHORIZATION_ID, transport=transport,
                now=lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
            )
            result = collect_reference_assets(
                {
                    "selected_candidates": [first, second],
                    "download_policy": "INTERNAL_ANALYSIS_ONLY",
                    "idempotency_key": "media-expired-continue",
                },
                downloader=adapter,
                storage=ResearchLibraryAdapter(Path(d)),
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )
            self.assertEqual([item.source_id for item in result.items], ["def456"])
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(adapter.receipts[0]["outcome"], "failed")
            self.assertEqual(adapter.receipts[0]["attempts"], 1)

    def test_candidate_deletion_removes_download_and_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            adapter = self.adapter(d, Transport())
            receipt = adapter.download(self.candidate())
            receipt_path = Path(d, "downloads", "receipts", "abc123.json")
            storage = ResearchLibraryAdapter(Path(d))
            storage.delete_record("abc123", reason="candidate expired")
            self.assertFalse(Path(receipt["storage_path"]).exists())
            self.assertFalse(receipt_path.exists())

    def test_internal_analysis_policy_preserves_unknown_rights_without_metadata_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            adapter = self.adapter(d, Transport())
            candidate = {**self.candidate(), "pii_detected": False, "brand_safety": 1.0}
            metadata_path = Path(d) / "metadata" / "abc123.json"
            before = metadata_path.read_bytes()
            result = collect_reference_assets(
                {"selected_candidates": [candidate], "download_policy": "INTERNAL_ANALYSIS_ONLY",
                 "idempotency_key": "media-1"},
                downloader=adapter, storage=ResearchLibraryAdapter(Path(d)),
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )
            self.assertEqual(result.items[0].lifecycle_state, "internal_analysis_only")
            self.assertEqual(result.items[0].rights_status, "UNKNOWN")
            self.assertEqual(metadata_path.read_bytes(), before)

    def test_cli_prints_persisted_receipt_and_zero_provider_calls(self):
        with tempfile.TemporaryDirectory() as d:
            adapter = self.adapter(d, Transport())
            candidate = {**self.candidate(), "pii_detected": False, "brand_safety": 1.0}
            request_path = Path(d) / "collect.json"
            request_path.write_text(json.dumps({
                "selected_candidates": [candidate], "download_policy": "INTERNAL_ANALYSIS_ONLY",
                "idempotency_key": "media-cli",
            }), encoding="utf-8")
            output = io.StringIO()
            from unittest.mock import patch
            with patch("ai_video_platform.skills.viral_research_asset_collection.cli.DirectMediaDownloadAdapter", return_value=adapter):
                with redirect_stdout(output):
                    self.assertEqual(main(["collect-reference-assets", "--input", str(request_path),
                        "--authorization-id", "FTG-P-RESEARCH-002", "--library-root", d,
                        "--now", "2026-07-22T00:00:00Z"]), 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["provider_calls"], 0)
            self.assertEqual(payload["download_attempts"], 1)
            self.assertTrue(Path(d, "downloads", "receipts", "abc123.json").exists())
            self.assertEqual(payload["download_receipts"][0]["lifecycle_state"], "internal_analysis_only")
