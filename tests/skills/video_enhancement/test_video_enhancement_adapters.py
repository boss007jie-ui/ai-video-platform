from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_enhancement import (
    EnhancementError,
    EnhancementErrorCode,
    FakeVideoEnhancementAdapter,
    InMemoryEnhancementLedger,
    RejectingVideoEnhancementAdapter,
    VideoEnhancementInterface,
)
from tests.skills.video_enhancement.test_video_enhancement_interface import NOW, SYNTHETIC_MP4, enhancement_request


class VideoEnhancementAdapterTests(unittest.TestCase):
    def test_fake_full_lifecycle_emits_safe_receipts_and_zero_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = enhancement_request(media)
            adapter = FakeVideoEnhancementAdapter(poll_states=("running", "succeeded"))
            ledger = InMemoryEnhancementLedger()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=ledger)

            submitted = interface.submit_enhancement(request, now=NOW)
            first_poll = interface.poll_enhancement(submitted["job_id"], now=NOW)
            succeeded = interface.poll_enhancement(submitted["job_id"], now=NOW)
            downloaded = interface.download_enhancement(submitted["job_id"], now=NOW)

        self.assertEqual(submitted["state"], "submitted")
        self.assertEqual(first_poll["state"], "polling")
        self.assertEqual(succeeded["state"], "succeeded")
        self.assertEqual(downloaded["state"], "downloaded")
        receipt = downloaded["receipt"]
        self.assertEqual(receipt["authorization_id"], "FTG-0-20260720-001")
        self.assertEqual(receipt["work_item_id"], "FT-05-002")
        self.assertEqual(receipt["state_history"], [
            "submitting", "submitted", "polling", "succeeded", "downloaded",
        ])
        self.assertEqual(receipt["input_summary"]["rights_basis"], "SYNTHETIC")
        self.assertEqual([item["type"] for item in receipt["operations"]], [
            "upscale", "frame_interpolation", "denoise_restore",
        ])
        self.assertTrue(receipt["cost_estimate"]["estimate_only"])
        self.assertFalse(receipt["provider_network_performed"])
        self.assertTrue(receipt["provider_execution_performed"])
        self.assertTrue(receipt["provider_job_id_digest"].startswith("sha256:"))
        self.assertNotIn(adapter.last_provider_job_id, json.dumps(receipt))
        self.assertNotIn(str(media.parent), json.dumps(receipt))
        self.assertEqual(receipt["output"]["media_type"], "video/mp4")
        self.assertTrue(receipt["output"]["sha256"].startswith("sha256:"))
        self.assertEqual(adapter.network_calls, 0)

    def test_rejecting_adapter_fails_closed_with_failure_receipt_and_zero_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = RejectingVideoEnhancementAdapter()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=InMemoryEnhancementLedger())

            with self.assertRaises(EnhancementError) as captured:
                interface.submit_enhancement(enhancement_request(media), now=NOW)

        self.assertEqual(captured.exception.code, EnhancementErrorCode.PROVIDER_REJECTED)
        receipt = captured.exception.details["receipt"]
        self.assertEqual(receipt["state"], "failed")
        self.assertEqual(receipt["state_history"], ["submitting", "failed"])
        self.assertEqual(receipt["error_code"], "PROVIDER_REJECTED")
        self.assertFalse(receipt["provider_network_performed"])
        self.assertEqual(adapter.network_calls, 0)

    def test_download_digest_mismatch_transitions_to_failed_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = FakeVideoEnhancementAdapter(corrupt_download=True)
            interface = VideoEnhancementInterface(adapter=adapter, ledger=InMemoryEnhancementLedger())
            submitted = interface.submit_enhancement(enhancement_request(media), now=NOW)
            interface.poll_enhancement(submitted["job_id"], now=NOW)

            with self.assertRaises(EnhancementError) as captured:
                interface.download_enhancement(submitted["job_id"], now=NOW)

        self.assertEqual(captured.exception.code, EnhancementErrorCode.DOWNLOAD_INTEGRITY_FAILED)
        receipt = captured.exception.details["receipt"]
        self.assertEqual(receipt["state"], "failed")
        self.assertEqual(receipt["state_history"][-2:], ["succeeded", "failed"])
        self.assertIsNone(receipt["output"])
        self.assertFalse(receipt["provider_network_performed"])

    def test_cancel_and_ledger_only_recovery_preserve_zero_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = FakeVideoEnhancementAdapter(poll_states=("running",))
            ledger = InMemoryEnhancementLedger()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=ledger)
            submitted = interface.submit_enhancement(enhancement_request(media), now=NOW)
            cancelled = interface.cancel_enhancement(submitted["job_id"], now=NOW)
            recovered = interface.recover_enhancement(submitted["job_id"], now=NOW)

        self.assertEqual(cancelled["receipt"]["state_history"], ["submitting", "submitted", "cancelled"])
        self.assertTrue(recovered["recovered"])
        self.assertEqual(recovered["state"], "cancelled")
        self.assertEqual(adapter.network_calls, 0)

    def test_poll_retry_exhaustion_enters_recovery_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = FakeVideoEnhancementAdapter(poll_failures=3)
            interface = VideoEnhancementInterface(adapter=adapter, ledger=InMemoryEnhancementLedger())
            submitted = interface.submit_enhancement(enhancement_request(media), now=NOW)
            with self.assertRaises(EnhancementError) as captured:
                interface.poll_enhancement(submitted["job_id"], now=NOW)

        self.assertEqual(captured.exception.code, EnhancementErrorCode.PROVIDER_RETRY_EXHAUSTED)
        self.assertEqual(captured.exception.details["receipt"]["state_history"], [
            "submitting", "submitted", "recovery_required",
        ])
        receipt = captured.exception.details["receipt"]
        self.assertEqual(receipt["error_code"], "PROVIDER_RETRY_EXHAUSTED")
        self.assertTrue(receipt["retryable"])
        self.assertEqual(receipt["error_summary"], "enhancement poll retry budget is exhausted")
        self.assertFalse(receipt["provider_network_performed"])

    def test_idempotent_replay_is_stable_and_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = FakeVideoEnhancementAdapter()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=InMemoryEnhancementLedger())
            request = enhancement_request(media)
            first = interface.submit_enhancement(request, now=NOW)
            replay = interface.submit_enhancement(request, now=NOW)
            changed = enhancement_request(media)
            changed["operations"][-1]["strength"] = 0.3
            with self.assertRaises(EnhancementError) as captured:
                interface.submit_enhancement(changed, now=NOW)

        self.assertEqual(first["job_id"], replay["job_id"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(adapter.submit_count, 1)
        self.assertEqual(captured.exception.code, EnhancementErrorCode.IDEMPOTENCY_MISMATCH)

    def test_provider_failed_state_has_stable_failure_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            interface = VideoEnhancementInterface(
                adapter=FakeVideoEnhancementAdapter(poll_states=("failed",)),
                ledger=InMemoryEnhancementLedger(),
            )
            submitted = interface.submit_enhancement(enhancement_request(media), now=NOW)
            failed = interface.poll_enhancement(submitted["job_id"], now=NOW)

        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["receipt"]["error_code"], "PROVIDER_REJECTED")
        self.assertFalse(failed["receipt"]["retryable"])
        self.assertEqual(failed["receipt"]["error_summary"], "adapter reported enhancement failure")

    def test_adapter_error_is_redacted_before_ledger_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = RejectingVideoEnhancementAdapter()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=InMemoryEnhancementLedger())
            from ai_video_platform.skills.video_enhancement.adapters import AdapterFailure
            with patch.object(adapter, "submit", side_effect=AdapterFailure("PROVIDER_REJECTED", "Bearer abcdefghijklmnopqrstuvwxyz012345", retryable=False)):
                with self.assertRaises(EnhancementError) as captured:
                    interface.submit_enhancement(enhancement_request(media), now=NOW)

        serialized = json.dumps(captured.exception.details)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz012345", serialized)
        self.assertEqual(captured.exception.details["receipt"]["error_summary"], "[REDACTED]")

    def test_network_marked_adapter_is_rejected_before_any_method_call(self) -> None:
        class NetworkMarkedAdapter(FakeVideoEnhancementAdapter):
            execution_mode = "provider"
            network_performed = True

        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = NetworkMarkedAdapter()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=InMemoryEnhancementLedger())
            with self.assertRaises(EnhancementError) as captured:
                interface.submit_enhancement(enhancement_request(media), now=NOW)
        self.assertEqual(captured.exception.code, EnhancementErrorCode.NETWORK_BLOCKED)
        self.assertEqual(adapter.submit_count, 0)

        class SpoofedOfflineAdapter(FakeVideoEnhancementAdapter):
            execution_mode = "offline_adapter"
            network_performed = False

        spoofed = SpoofedOfflineAdapter()
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            with self.assertRaises(EnhancementError) as spoofed_error:
                VideoEnhancementInterface(adapter=spoofed, ledger=InMemoryEnhancementLedger()).submit_enhancement(enhancement_request(media), now=NOW)
        self.assertEqual(spoofed_error.exception.code, EnhancementErrorCode.NETWORK_BLOCKED)
        self.assertEqual(spoofed.submit_count, 0)

    def test_failed_submission_replay_preserves_error_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = RejectingVideoEnhancementAdapter()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=InMemoryEnhancementLedger())
            request = enhancement_request(media)
            with patch.object(adapter, "submit", wraps=adapter.submit) as submit:
                with self.assertRaises(EnhancementError):
                    interface.submit_enhancement(request, now=NOW)
                with self.assertRaises(EnhancementError) as replayed:
                    interface.submit_enhancement(request, now=NOW)
        self.assertEqual(replayed.exception.code, EnhancementErrorCode.PROVIDER_REJECTED)
        self.assertEqual(replayed.exception.details["receipt"]["state"], "failed")
        self.assertEqual(submit.call_count, 1)

    def test_unexpected_adapter_exceptions_transition_and_stay_machine_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = FakeVideoEnhancementAdapter()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=InMemoryEnhancementLedger())
            submitted = interface.submit_enhancement(enhancement_request(media), now=NOW)
            with patch.object(adapter, "poll", side_effect=RuntimeError("Bearer abcdefghijklmnopqrstuvwxyz012345")):
                with self.assertRaises(EnhancementError) as captured:
                    interface.poll_enhancement(submitted["job_id"], now=NOW)
        self.assertEqual(captured.exception.code, EnhancementErrorCode.PROVIDER_REJECTED)
        self.assertEqual(captured.exception.details["receipt"]["state"], "recovery_required")
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz012345", json.dumps(captured.exception.details))

    def test_unexpected_cancel_and_download_exceptions_have_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            cancel_adapter = FakeVideoEnhancementAdapter()
            cancel_interface = VideoEnhancementInterface(adapter=cancel_adapter, ledger=InMemoryEnhancementLedger())
            cancel_job = cancel_interface.submit_enhancement(enhancement_request(media), now=NOW)["job_id"]
            with patch.object(cancel_adapter, "cancel", side_effect=RuntimeError("unexpected cancel")):
                with self.assertRaises(EnhancementError) as cancel_error:
                    cancel_interface.cancel_enhancement(cancel_job, now=NOW)

            download_request = enhancement_request(media)
            download_request["idempotency_key"] = "ft-05-002-exploding-download"
            download_adapter = FakeVideoEnhancementAdapter()
            download_interface = VideoEnhancementInterface(adapter=download_adapter, ledger=InMemoryEnhancementLedger())
            download_job = download_interface.submit_enhancement(download_request, now=NOW)["job_id"]
            download_interface.poll_enhancement(download_job, now=NOW)
            with patch.object(download_adapter, "download", side_effect=RuntimeError("unexpected download")):
                with self.assertRaises(EnhancementError) as download_error:
                    download_interface.download_enhancement(download_job, now=NOW)

        self.assertEqual(cancel_error.exception.details["receipt"]["state"], "recovery_required")
        self.assertEqual(download_error.exception.details["receipt"]["state"], "failed")

    def test_sensitive_download_failure_is_redacted_in_public_ledger(self) -> None:
        from ai_video_platform.skills.video_enhancement.adapters import AdapterFailure

        secret = "Bearer abcdefghijklmnopqrstuvwxyz012345"
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = FakeVideoEnhancementAdapter()
            ledger = InMemoryEnhancementLedger()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=ledger)
            job_id = interface.submit_enhancement(enhancement_request(media), now=NOW)["job_id"]
            interface.poll_enhancement(job_id, now=NOW)
            with patch.object(adapter, "download", side_effect=AdapterFailure("PROVIDER_REJECTED", secret, retryable=False)):
                with self.assertRaises(EnhancementError) as captured:
                    interface.download_enhancement(job_id, now=NOW)
            raw_record = ledger.get(job_id)

        self.assertNotIn(secret, json.dumps(raw_record))
        self.assertEqual(raw_record["error_summary"], "[REDACTED]")
        self.assertEqual(captured.exception.details["receipt"]["error_summary"], "[REDACTED]")

    def test_submit_timeout_and_unsupported_state_receipts_are_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)

            submit_interface = VideoEnhancementInterface(
                adapter=FakeVideoEnhancementAdapter(submit_failures=3),
                ledger=InMemoryEnhancementLedger(),
            )
            with self.assertRaises(EnhancementError) as submit_error:
                submit_interface.submit_enhancement(enhancement_request(media), now=NOW)

            timeout_request = enhancement_request(media)
            timeout_request["idempotency_key"] = "ft-05-002-timeout"
            timeout_adapter = FakeVideoEnhancementAdapter(poll_states=("running",))
            timeout_interface = VideoEnhancementInterface(adapter=timeout_adapter, ledger=InMemoryEnhancementLedger())
            timeout_job = timeout_interface.submit_enhancement(timeout_request, now=NOW)["job_id"]
            timed_out = timeout_interface.poll_enhancement(timeout_job, now=NOW + timedelta(seconds=120))

            cancel_request = enhancement_request(media)
            cancel_request["idempotency_key"] = "ft-05-002-timeout-cancel-failure"
            cancel_adapter = FakeVideoEnhancementAdapter(poll_states=("running",))
            cancel_interface = VideoEnhancementInterface(adapter=cancel_adapter, ledger=InMemoryEnhancementLedger())
            cancel_job = cancel_interface.submit_enhancement(cancel_request, now=NOW)["job_id"]
            with patch.object(cancel_adapter, "cancel", side_effect=RuntimeError("cancel failed")):
                with self.assertRaises(EnhancementError) as cancel_error:
                    cancel_interface.poll_enhancement(cancel_job, now=NOW + timedelta(seconds=120))

            unsupported_request = enhancement_request(media)
            unsupported_request["idempotency_key"] = "ft-05-002-unsupported-state"
            unsupported_interface = VideoEnhancementInterface(
                adapter=FakeVideoEnhancementAdapter(poll_states=("unknown",)),
                ledger=InMemoryEnhancementLedger(),
            )
            unsupported_job = unsupported_interface.submit_enhancement(unsupported_request, now=NOW)["job_id"]
            with self.assertRaises(EnhancementError) as unsupported_error:
                unsupported_interface.poll_enhancement(unsupported_job, now=NOW)

        submit_receipt = submit_error.exception.details["receipt"]
        self.assertEqual((submit_receipt["error_code"], submit_receipt["retryable"], submit_receipt["error_summary"]), (
            "PROVIDER_RETRY_EXHAUSTED", True, "enhancement submit retry budget is exhausted",
        ))
        timeout_receipt = timed_out["receipt"]
        self.assertEqual((timeout_receipt["error_code"], timeout_receipt["retryable"], timeout_receipt["error_summary"]), (
            "PROVIDER_RETRY_EXHAUSTED", False, "enhancement execution timed out",
        ))
        cancel_receipt = cancel_error.exception.details["receipt"]
        self.assertEqual((cancel_receipt["error_code"], cancel_receipt["retryable"], cancel_receipt["error_summary"]), (
            "PROVIDER_REJECTED", False, "enhancement timeout cancellation failed",
        ))
        unsupported_receipt = unsupported_error.exception.details["receipt"]
        self.assertEqual((unsupported_receipt["error_code"], unsupported_receipt["retryable"], unsupported_receipt["error_summary"]), (
            "PROVIDER_REJECTED", False, "adapter returned an unsupported state",
        ))

    def test_cancelled_submission_replay_is_a_terminal_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = FakeVideoEnhancementAdapter()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=InMemoryEnhancementLedger())
            request = enhancement_request(media)
            job_id = interface.submit_enhancement(request, now=NOW)["job_id"]
            interface.cancel_enhancement(job_id, now=NOW)
            with self.assertRaises(EnhancementError) as replayed:
                interface.submit_enhancement(request, now=NOW)
        self.assertEqual(replayed.exception.code, EnhancementErrorCode.INVALID_TRANSITION)
        self.assertEqual(replayed.exception.details["receipt"]["state"], "cancelled")
        self.assertEqual(adapter.submit_count, 1)


if __name__ == "__main__":
    unittest.main()
