from __future__ import annotations

import json
from pathlib import Path
import tempfile
from threading import Barrier, Thread
from time import perf_counter
import unittest

from ai_video_platform.skills.product_knowledge import (
    InMemoryProductLibrary,
    FilesystemProductLibrary,
    ProductKnowledgeError,
    ProductKnowledgeErrorCode,
    ProductKnowledgeService,
)


class ProductLibraryAdapterTests(unittest.TestCase):
    def test_idempotent_replay_returns_original_result_and_mismatch_fails_closed(self) -> None:
        library = InMemoryProductLibrary()
        service = ProductKnowledgeService(library)
        request = {
            "identity": {"brand": "Acme", "model": "Glow"},
            "evidence_refs": ["evidence:synthetic-catalog"],
            "actor": "human:test",
            "reason": "Synthetic catalog registration",
            "idempotency_key": "create-product-001",
            "expected_library_revision": 0,
        }

        first = service.create_product(request)
        replay = service.create_product(request)

        self.assertEqual(replay, first)
        state = library.snapshot()
        self.assertEqual(state["revision"], 1)
        self.assertEqual(len(state["products"]), 1)
        self.assertEqual(len(state["audit"]), 1)
        self.assertEqual(state["audit"][0]["command"], "create-product")
        self.assertEqual(state["audit"][0]["before_revision"], 0)
        self.assertEqual(state["audit"][0]["after_revision"], 1)

        ingest_request = {
            "product_id": first["product_id"],
            "facts": [
                {
                    "fact_id": "fact-idempotent",
                    "claim_type": "color",
                    "value": "red",
                    "status": "confirmed",
                    "inferred": False,
                    "provenance": ["evidence:synthetic-idempotent"],
                }
            ],
            "actor": "human:test",
            "reason": "Synthetic idempotent ingest",
            "idempotency_key": "ingest-product-001",
            "expected_product_version": 1,
            "expected_library_revision": 1,
        }
        ingested = service.ingest_product(ingest_request)
        ingest_replay = service.ingest_product(ingest_request)
        self.assertEqual(ingest_replay, ingested)
        self.assertEqual(library.snapshot()["revision"], 2)
        self.assertEqual(len(library.snapshot()["products"][first["product_id"]]["facts"]), 1)

        with self.assertRaises(ProductKnowledgeError) as captured:
            service.create_product({**request, "identity": {"brand": "Acme", "model": "Changed"}})
        self.assertEqual(captured.exception.code, ProductKnowledgeErrorCode.IDEMPOTENCY_MISMATCH)

    def test_filesystem_adapter_writes_atomically_and_restores_verified_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "product-library"
            library = FilesystemProductLibrary(root)
            service = ProductKnowledgeService(library)
            created = service.create_product(
                {
                    "identity": {"brand": "Acme", "model": "Glow"},
                    "evidence_refs": ["evidence:synthetic-catalog"],
                    "actor": "human:test",
                    "reason": "Synthetic catalog registration",
                    "idempotency_key": "fs-product",
                    "expected_library_revision": 0,
                }
            )
            snapshot_path = service.backup_library(
                {"actor": "operator:test", "reason": "Pre-change recovery point"}
            )
            sku_request = {
                "product_id": created["product_id"],
                "identity": {"sku_code": "GLOW-RED"},
                "evidence_refs": ["evidence:synthetic-red"],
                "actor": "human:test",
                "reason": "Synthetic red variant",
                "idempotency_key": "fs-sku",
                "expected_product_version": 1,
                "expected_library_revision": 1,
            }
            service.create_sku(sku_request)

            restored = service.restore_library(
                {
                    "snapshot_path": snapshot_path,
                    "expected_library_revision": 2,
                    "actor": "operator:test",
                    "reason": "Synthetic recovery drill",
                }
            )

            self.assertEqual(restored["revision"], 3)
            state = library.snapshot()
            self.assertEqual(state["products"][created["product_id"]]["skus"], {})
            self.assertEqual([entry["command"] for entry in state["audit"]], ["create-product", "create-sku", "restore-snapshot"])
            on_disk = json.loads((root / "metadata" / "library.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk, state)
            self.assertEqual(list((root / "metadata").glob("*.tmp")), [])
            with self.assertRaises(ProductKnowledgeError) as restored_out:
                service.create_sku(sku_request)
            self.assertEqual(restored_out.exception.code, ProductKnowledgeErrorCode.IDEMPOTENCY_RESTORED_OUT)

    def test_concurrent_filesystem_updates_allow_one_writer_and_reject_stale_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "product-library"
            first_service = ProductKnowledgeService(FilesystemProductLibrary(root))
            created = first_service.create_product(
                {
                    "identity": {"brand": "Acme", "model": "Glow"},
                    "evidence_refs": ["evidence:synthetic-catalog"],
                    "actor": "human:test",
                    "reason": "Synthetic catalog registration",
                    "idempotency_key": "concurrent-product",
                    "expected_library_revision": 0,
                }
            )
            services = [
                ProductKnowledgeService(FilesystemProductLibrary(root)),
                ProductKnowledgeService(FilesystemProductLibrary(root)),
            ]
            barrier = Barrier(2)
            outcomes: list[object] = []

            def create_variant(index: int) -> None:
                request = {
                    "product_id": created["product_id"],
                    "identity": {"sku_code": f"GLOW-{index}"},
                    "evidence_refs": [f"evidence:synthetic-{index}"],
                    "actor": f"human:test-{index}",
                    "reason": "Synthetic concurrent variant",
                    "idempotency_key": f"concurrent-sku-{index}",
                    "expected_product_version": 1,
                    "expected_library_revision": 1,
                }
                barrier.wait()
                try:
                    outcomes.append(services[index].create_sku(request))
                except ProductKnowledgeError as exc:
                    outcomes.append(exc)

            threads = [Thread(target=create_variant, args=(index,)) for index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            successes = [outcome for outcome in outcomes if isinstance(outcome, dict)]
            failures = [outcome for outcome in outcomes if isinstance(outcome, ProductKnowledgeError)]
            self.assertEqual(len(successes), 1)
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0].code, ProductKnowledgeErrorCode.LIBRARY_VERSION_CONFLICT)
            self.assertTrue(failures[0].retryable)
            final_state = FilesystemProductLibrary(root).snapshot()
            self.assertEqual(final_state["revision"], 2)
            self.assertEqual(len(final_state["products"][created["product_id"]]["skus"]), 1)

    def test_writer_lock_timeout_fails_closed_without_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "product-library"
            library = FilesystemProductLibrary(root, lock_timeout_seconds=0.02)
            lock_path = root / "locks" / "writer.lock"
            lock_path.write_text("synthetic-active-writer", encoding="ascii")
            try:
                with self.assertRaises(ProductKnowledgeError) as captured:
                    ProductKnowledgeService(library).create_product(
                        {
                            "identity": {"brand": "Acme", "model": "Glow"},
                            "evidence_refs": ["evidence:synthetic"],
                            "actor": "human:test",
                            "reason": "Synthetic lock timeout",
                            "idempotency_key": "lock-timeout-product",
                            "expected_library_revision": 0,
                        }
                    )
                self.assertEqual(captured.exception.code, ProductKnowledgeErrorCode.PRODUCT_LIBRARY_LOCK_TIMEOUT)
                self.assertTrue(captured.exception.retryable)
            finally:
                lock_path.unlink()
            self.assertEqual(library.snapshot()["revision"], 0)

    def test_in_memory_match_performance_budget(self) -> None:
        library = InMemoryProductLibrary()
        service = ProductKnowledgeService(library)
        for index in range(100):
            service.create_product(
                {
                    "identity": {"brand": "Acme", "model": f"Model-{index}"},
                    "evidence_refs": [f"evidence:synthetic-{index}"],
                    "actor": "human:test",
                    "reason": "Synthetic performance fixture",
                    "idempotency_key": f"performance-product-{index}",
                    "expected_library_revision": index,
                }
            )
        started = perf_counter()
        for _ in range(500):
            result = service.match_product({"clues": {"brand": "Acme", "model": "Model-50"}})
            self.assertEqual(result["status"], "exact")
        elapsed = perf_counter() - started
        self.assertLess(elapsed, 2.0, f"500 in-memory matches exceeded 2.0s budget: {elapsed:.3f}s")
