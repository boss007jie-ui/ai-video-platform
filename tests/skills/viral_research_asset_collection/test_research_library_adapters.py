from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_video_platform.skills.viral_research_asset_collection import ErrorCode, SkillError
from ai_video_platform.skills.viral_research_asset_collection.storage import InMemoryResearchLibraryAdapter, ResearchLibraryAdapter


RECORD = {
    "source_id": "source-1", "source_url": "https://example.invalid/source-1",
    "lifecycle_state": "retained", "rights_status": "PUBLIC", "pii_detected": False,
    "retention_until": "2026-08-20T00:00:00Z", "expires_at": "2026-08-01T00:00:00Z",
}


class ResearchLibraryAdapterTests(unittest.TestCase):
    def test_filesystem_atomic_create_never_clobbers_a_racing_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = ResearchLibraryAdapter(root)
            target = root / "metadata" / "source-1.json"

            def racing_link(source, destination):
                del source
                Path(destination).write_bytes(b"racing-writer")
                raise FileExistsError

            with patch("ai_video_platform.skills.viral_research_asset_collection.storage.os.link", side_effect=racing_link):
                with self.assertRaises(SkillError) as caught:
                    adapter.write_record(RECORD, idempotency_key="race")
            self.assertEqual(caught.exception.code, ErrorCode.STORAGE_CONFLICT)
            self.assertEqual(target.read_bytes(), b"racing-writer")
            self.assertFalse(list(root.rglob("*.tmp")))

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

    def test_filesystem_idempotency_and_audit_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ResearchLibraryAdapter(root).write_record(RECORD, idempotency_key="write-1")
            restarted = ResearchLibraryAdapter(root)
            restarted.write_record(RECORD, idempotency_key="write-1")
            with self.assertRaises(SkillError) as caught:
                restarted.write_record({**RECORD, "rights_status": "UNKNOWN"}, idempotency_key="write-1")
            self.assertEqual(caught.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)
            with self.assertRaises(SkillError) as caught:
                restarted.write_record({**RECORD, "rights_status": "UNKNOWN"}, idempotency_key="write-2")
            self.assertEqual(caught.exception.code, ErrorCode.STORAGE_CONFLICT)
            self.assertTrue((root / "audit" / "lifecycle.jsonl").is_file())
            self.assertTrue((root / "audit" / "idempotency.json").is_file())
            lifecycle_index = root / "audit" / "lifecycle-index.json"
            self.assertTrue(lifecycle_index.is_file())
            lifecycle_index.unlink()
            ResearchLibraryAdapter(root).write_record(RECORD, idempotency_key="write-1")
            repaired = json.loads(lifecycle_index.read_text(encoding="utf-8"))
            self.assertIn("write-1", repaired)

    def test_request_claim_and_completed_replay_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = ResearchLibraryAdapter(root)
            self.assertIsNone(adapter.begin_request("research", "request-1", "a" * 64))
            adapter.complete_request(
                "research", "request-1", "a" * 64,
                {"status": "COMPLETED", "request_digest": "a" * 64, "provider_calls": 1, "partial": False, "candidates": []},
            )
            replay = ResearchLibraryAdapter(root).begin_request("research", "request-1", "a" * 64)
            self.assertEqual(replay["provider_calls"], 1)
            with self.assertRaises(SkillError) as caught:
                ResearchLibraryAdapter(root).begin_request("research", "request-1", "b" * 64)
            self.assertEqual(caught.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)

    def test_same_source_id_cannot_move_or_change_content(self) -> None:
        memory = InMemoryResearchLibraryAdapter()
        memory.write_record(RECORD, idempotency_key="first")
        with self.assertRaises(SkillError) as caught:
            memory.write_record({**RECORD, "rights_status": "UNKNOWN"}, idempotency_key="changed")
        self.assertEqual(caught.exception.code, ErrorCode.STORAGE_CONFLICT)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ResearchLibraryAdapter(root).write_record(RECORD, idempotency_key="first")
            moved = {**RECORD, "lifecycle_state": "quarantined", "pii_detected": True}
            with self.assertRaises(SkillError) as caught:
                ResearchLibraryAdapter(root).write_record(moved, idempotency_key="moved")
            self.assertEqual(caught.exception.code, ErrorCode.STORAGE_CONFLICT)
            self.assertFalse((root / "quarantine" / "source-1.json").exists())

    def test_filesystem_rejects_symlink_root_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            actual = base / "actual"
            actual.mkdir()
            linked = base / "linked"
            try:
                os.symlink(actual, linked, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            with self.assertRaises(SkillError) as caught:
                ResearchLibraryAdapter(linked)
            self.assertEqual(caught.exception.code, ErrorCode.PATH_FORBIDDEN)

    def test_filesystem_rejects_symlink_ancestor_and_dangling_audit_target_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            actual = base / "actual"
            actual.mkdir()
            linked_parent = base / "linked-parent"
            try:
                os.symlink(actual, linked_parent, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            with self.assertRaises(SkillError) as caught:
                ResearchLibraryAdapter(linked_parent / "new-root")
            self.assertEqual(caught.exception.code, ErrorCode.PATH_FORBIDDEN)

            root = base / "root"
            adapter = ResearchLibraryAdapter(root)
            outside = base / "outside-lifecycle.jsonl"
            lifecycle = root / "audit" / "lifecycle.jsonl"
            lifecycle.unlink(missing_ok=True)
            os.symlink(outside, lifecycle)
            with self.assertRaises(SkillError) as caught:
                adapter.write_record(RECORD, idempotency_key="dangling")
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
