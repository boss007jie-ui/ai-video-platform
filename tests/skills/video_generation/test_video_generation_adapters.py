from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_generation import GenerationError, GenerationErrorCode, VideoGenerationInterface
from ai_video_platform.skills.video_generation.adapters import FakeVideoProviderAdapter, NetworkBlockedVideoProviderAdapter, RejectingVideoProviderAdapter
from ai_video_platform.skills.video_generation.ledger import InMemoryVideoExecutionLedger
from tests.skills.video_generation.test_video_generation_interface import NOW, generation_request


class VideoGenerationAdapterTests(unittest.TestCase):
    def make_interface(self, adapter: object | None = None, ledger: object | None = None) -> VideoGenerationInterface:
        return VideoGenerationInterface(
            adapter=adapter or FakeVideoProviderAdapter(),
            ledger=ledger or InMemoryVideoExecutionLedger(),
        )

    def assert_code(self, code: GenerationErrorCode, operation) -> GenerationError:
        with self.assertRaises(GenerationError) as captured:
            operation()
        self.assertEqual(captured.exception.code, code)
        return captured.exception

    def test_submit_poll_download_happy_path_and_asset_manifest_request(self) -> None:
        adapter = FakeVideoProviderAdapter(poll_states=("running", "succeeded"))
        interface = self.make_interface(adapter)
        submitted = interface.submit_video(generation_request(), now=NOW)
        self.assertEqual(submitted["state"], "submitted")
        self.assertFalse(submitted["replayed"])
        self.assertNotIn("credential", str(submitted).lower())
        self.assertEqual(interface.poll_video(submitted["job_id"], now=NOW)["state"], "running")
        succeeded = interface.poll_video(submitted["job_id"], now=NOW)
        self.assertEqual(succeeded["state"], "succeeded")
        downloaded = interface.download_video(submitted["job_id"], now=NOW)
        self.assertEqual(downloaded["state"], "downloaded")
        self.assertEqual(downloaded["asset_manifest_request"]["contract_status"], "DRAFT_UNREGISTERED")
        self.assertTrue(downloaded["asset_manifest_request"]["sha256"].startswith("sha256:"))
        self.assertFalse(downloaded["provider_network_performed"])
        self.assertIsNotNone(adapter.last_submission)
        self.assertNotIn("credential_ref", str(adapter.last_submission))

    def test_exact_idempotent_replay_and_mismatch(self) -> None:
        interface = self.make_interface()
        request = generation_request()
        first = interface.submit_video(request, now=NOW)
        replay = interface.submit_video(request, now=NOW)
        self.assertEqual(replay["job_id"], first["job_id"])
        self.assertTrue(replay["replayed"])
        changed = generation_request()
        changed["output"]["quality"] = "other"
        self.assert_code(GenerationErrorCode.IDEMPOTENCY_MISMATCH, lambda: interface.submit_video(changed, now=NOW))

    def test_concurrency_and_request_limits_fail_closed(self) -> None:
        interface = self.make_interface(FakeVideoProviderAdapter(poll_states=("running",)))
        first = generation_request()
        first["budget"]["max_concurrency"] = 1
        interface.submit_video(first, now=NOW)
        second = generation_request()
        second["idempotency_key"] = "idem-video-002"
        self.assert_code(GenerationErrorCode.CONCURRENCY_LIMIT, lambda: interface.submit_video(second, now=NOW))

        interface = self.make_interface()
        request = generation_request()
        request["budget"]["max_requests"] = 1
        submitted = interface.submit_video(request, now=NOW)
        interface.poll_video(submitted["job_id"], now=NOW)
        second = generation_request()
        second["idempotency_key"] = "idem-video-002"
        second["budget"]["max_requests"] = 1
        self.assert_code(GenerationErrorCode.REQUEST_LIMIT, lambda: interface.submit_video(second, now=NOW))

    def test_concurrency_reservation_is_atomic_across_threads(self) -> None:
        interface = self.make_interface(FakeVideoProviderAdapter(poll_states=("running",)))
        requests = [generation_request(), generation_request()]
        requests[1]["idempotency_key"] = "idem-video-002"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(interface.submit_video, request, now=NOW) for request in requests]
        outcomes: list[str] = []
        for future in futures:
            try:
                outcomes.append(str(future.result()["state"]))
            except GenerationError as error:
                outcomes.append(error.code.value)
        self.assertEqual(sorted(outcomes), ["CONCURRENCY_LIMIT", "submitted"])

    def test_ledger_reads_are_snapshots(self) -> None:
        ledger = InMemoryVideoExecutionLedger()
        interface = self.make_interface(ledger=ledger)
        submitted = interface.submit_video(generation_request(), now=NOW)
        first = ledger.get(submitted["job_id"])
        first["state"] = "tampered"
        self.assertEqual(ledger.get(submitted["job_id"])["state"], "submitted")

    def test_retry_then_success_and_retry_exhaustion(self) -> None:
        interface = self.make_interface(FakeVideoProviderAdapter(submit_failures=2))
        submitted = interface.submit_video(generation_request(), now=NOW)
        self.assertEqual(submitted["attempts"], 3)

        request = generation_request()
        request["budget"]["max_attempts"] = 2
        interface = self.make_interface(FakeVideoProviderAdapter(submit_failures=3))
        self.assert_code(GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED, lambda: interface.submit_video(request, now=NOW))

    def test_timeout_and_cancel_are_terminal(self) -> None:
        interface = self.make_interface(FakeVideoProviderAdapter(poll_states=("running",)))
        submitted = interface.submit_video(generation_request(), now=NOW)
        timed_out = interface.poll_video(submitted["job_id"], now=NOW + timedelta(seconds=61))
        self.assertEqual(timed_out["state"], "timed_out")
        self.assert_code(GenerationErrorCode.INVALID_TRANSITION, lambda: interface.download_video(submitted["job_id"], now=NOW))

        interface = self.make_interface()
        submitted = interface.submit_video(generation_request(), now=NOW)
        cancelled = interface.cancel_video(submitted["job_id"], now=NOW)
        self.assertEqual(cancelled["state"], "cancelled")
        self.assert_code(GenerationErrorCode.INVALID_TRANSITION, lambda: interface.poll_video(submitted["job_id"], now=NOW))

    def test_download_digest_mismatch_fails_closed(self) -> None:
        interface = self.make_interface(FakeVideoProviderAdapter(poll_states=("succeeded",), corrupt_download=True))
        submitted = interface.submit_video(generation_request(), now=NOW)
        interface.poll_video(submitted["job_id"], now=NOW)
        self.assert_code(GenerationErrorCode.DOWNLOAD_INTEGRITY_FAILED, lambda: interface.download_video(submitted["job_id"], now=NOW))

    def test_recovery_uses_shared_ledger_without_resubmission(self) -> None:
        ledger = InMemoryVideoExecutionLedger()
        adapter = FakeVideoProviderAdapter(poll_states=("running", "succeeded"))
        first = self.make_interface(adapter, ledger)
        submitted = first.submit_video(generation_request(), now=NOW)
        recovered = self.make_interface(adapter, ledger).recover_video(submitted["job_id"], now=NOW)
        self.assertEqual(recovered["job_id"], submitted["job_id"])
        self.assertEqual(recovered["state"], "running")
        self.assertEqual(adapter.submit_count, 1)

    def test_rejecting_and_network_blocked_adapters_never_touch_network(self) -> None:
        for adapter, code in (
            (RejectingVideoProviderAdapter(), GenerationErrorCode.PROVIDER_REJECTED),
            (NetworkBlockedVideoProviderAdapter(), GenerationErrorCode.NETWORK_BLOCKED),
        ):
            with self.subTest(adapter=type(adapter).__name__):
                error = self.assert_code(code, lambda: self.make_interface(adapter).submit_video(generation_request(), now=NOW))
                self.assertFalse(error.retryable)
                self.assertEqual(adapter.network_calls, 0)

    def test_failed_submission_is_idempotently_replayed_as_the_same_error(self) -> None:
        interface = self.make_interface(RejectingVideoProviderAdapter())
        request = generation_request()
        self.assert_code(GenerationErrorCode.PROVIDER_REJECTED, lambda: interface.submit_video(request, now=NOW))
        replay = self.assert_code(GenerationErrorCode.PROVIDER_REJECTED, lambda: interface.submit_video(request, now=NOW))
        self.assertIn("Previously recorded", str(replay))

    def test_unexpected_adapter_exception_is_suppressed_and_redacted(self) -> None:
        raw_value = "Bearer " + "synthetic" + "H" * 24

        class LeakyAdapter(RejectingVideoProviderAdapter):
            def submit(self, request):
                raise ValueError(raw_value)

        error = self.assert_code(
            GenerationErrorCode.PROVIDER_REJECTED,
            lambda: self.make_interface(LeakyAdapter()).submit_video(generation_request(), now=NOW),
        )
        self.assertIsNone(error.__cause__)
        self.assertNotIn(raw_value, str(error))


if __name__ == "__main__":
    unittest.main()
