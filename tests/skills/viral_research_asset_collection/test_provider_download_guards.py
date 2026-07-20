from __future__ import annotations

from datetime import datetime, timezone
import unittest

from ai_video_platform.skills.viral_research_asset_collection import ErrorCode, SkillError, collect_reference_assets
from ai_video_platform.skills.viral_research_asset_collection.adapters import (
    FakeCollectionAdapter, FakeDownloadAdapter, RejectingCollectionAdapter, RejectingDownloadAdapter,
)
from ai_video_platform.skills.viral_research_asset_collection.storage import InMemoryResearchLibraryAdapter


NOW = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)


class ProviderDownloadGuardTests(unittest.TestCase):
    def test_rejecting_adapters_fail_closed(self) -> None:
        provider = RejectingCollectionAdapter()
        with self.assertRaises(SkillError) as caught:
            provider.fetch("query", limit=1, timeout_seconds=1)
        self.assertEqual(caught.exception.code, ErrorCode.PROVIDER_FORBIDDEN)
        self.assertEqual(provider.attempt_count, 1)
        downloader = RejectingDownloadAdapter()
        with self.assertRaises(SkillError) as caught:
            downloader.download({"source_id": "x"})
        self.assertEqual(caught.exception.code, ErrorCode.DOWNLOAD_FORBIDDEN)
        self.assertEqual(downloader.attempt_count, 1)

    def test_fake_collection_is_deterministic_and_capped(self) -> None:
        rows = [{"source_id": "1"}, {"source_id": "2"}]
        adapter = FakeCollectionAdapter(rows)
        self.assertEqual(adapter.fetch("q", limit=1, timeout_seconds=1), (rows[0],))
        self.assertEqual(adapter.fetch("q", limit=1, timeout_seconds=1), (rows[0],))

    def test_metadata_only_never_downloads_and_free_first_requires_rights(self) -> None:
        selected = [{
            "source_id": "x", "source_url": "https://example.invalid/x", "rights_status": "UNKNOWN",
            "pii_detected": False, "expires_at": "2026-07-21T00:00:00Z",
        }]
        fake = FakeDownloadAdapter()
        storage = InMemoryResearchLibraryAdapter()
        result = collect_reference_assets(
            {"selected_candidates": selected, "download_policy": "METADATA_ONLY", "idempotency_key": "c-1"},
            downloader=fake, storage=storage, now=NOW,
        )
        self.assertEqual(fake.attempt_count, 0)
        self.assertEqual(result.items[0].lifecycle_state, "metadata_only")
        with self.assertRaises(SkillError) as caught:
            collect_reference_assets(
                {"selected_candidates": selected, "download_policy": "FREE_FIRST", "idempotency_key": "c-2"},
                downloader=fake, storage=storage, now=NOW,
            )
        self.assertEqual(caught.exception.code, ErrorCode.RIGHTS_FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
