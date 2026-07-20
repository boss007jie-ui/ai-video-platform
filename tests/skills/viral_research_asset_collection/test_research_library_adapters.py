from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.viral_research_asset_collection import ErrorCode, SkillError
from ai_video_platform.skills.viral_research_asset_collection.storage import InMemoryResearchLibraryAdapter, ResearchLibraryAdapter


RECORD = {
    "source_id": "source-1", "source_url": "https://example.invalid/source-1",
    "lifecycle_state": "retained", "rights_status": "PUBLIC", "pii_detected": False,
    "retention_until": "2026-08-20T00:00:00Z", "expires_at": "2026-08-01T00:00:00Z",
}


class ResearchLibraryAdapterTests(unittest.TestCase):
    def test_memory_adapter_is_idempotent_and_audits_deletion(self) -> None:
        adapter = InMemoryResearchLibraryAdapter()
        adapter.write_record(RECORD, idempotency_key="write-1")
        adapter.write_record(RECORD, idempotency_key="write-1")
        with self.assertRaises(SkillError) as caught:
            adapter.write_record({**RECORD, "rights_status": "UNKNOWN"}, idempotency_key="write-1")
        self.assertEqual(caught.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)
        adapter.delete_record("source-1", reason="retention_expired")
        self.assertNotIn("source-1", adapter.records)
        self.assertEqual(adapter.audit_log[-1]["action"], "deleted")

    def test_filesystem_adapter_writes_atomic_metadata_and_blocks_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = ResearchLibraryAdapter(root)
            adapter.write_record(RECORD, idempotency_key="write-1")
            stored = root / "metadata" / "source-1.json"
            self.assertTrue(stored.is_file())
            self.assertEqual(json.loads(stored.read_text(encoding="utf-8"))["source_id"], "source-1")
            self.assertFalse(list(root.rglob("*.tmp")))
            with self.assertRaises(SkillError) as caught:
                adapter.write_record({**RECORD, "source_id": "../escape"}, idempotency_key="escape")
            self.assertEqual(caught.exception.code, ErrorCode.PATH_FORBIDDEN)

    def test_quarantine_is_separate_and_retention_is_not_extended(self) -> None:
        adapter = InMemoryResearchLibraryAdapter()
        quarantined = {**RECORD, "source_id": "q-1", "lifecycle_state": "quarantined", "pii_detected": True}
        adapter.write_record(quarantined, idempotency_key="q")
        self.assertIn("q-1", adapter.quarantine)
        with self.assertRaises(SkillError) as caught:
            adapter.write_record({**quarantined, "retention_until": "2027-01-01T00:00:00Z"}, idempotency_key="q2")
        self.assertEqual(caught.exception.code, ErrorCode.RETENTION_EXTENSION_FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
