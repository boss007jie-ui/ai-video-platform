from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_enhancement import FakeVideoEnhancementAdapter, InMemoryEnhancementLedger, VideoEnhancementInterface
from ai_video_platform.skills.video_enhancement.cli import run_cli
from tests.skills.video_enhancement.test_video_enhancement_interface import NOW, SYNTHETIC_MP4, enhancement_request


class VideoEnhancementCliTests(unittest.TestCase):
    def test_inspect_succeeds_but_default_execution_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            request = enhancement_request(media)
            inspected = run_cli("inspect-enhancement-request", request, now=NOW)
            rejected = run_cli("submit-enhancement", request, now=NOW)

        self.assertTrue(inspected["ok"])
        self.assertEqual(inspected["exit_code"], 0)
        self.assertEqual(inspected["result"]["status"], "ready")
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["exit_code"], 2)
        self.assertEqual(rejected["error"]["code"], "NETWORK_BLOCKED")

    def test_all_six_commands_use_the_injected_offline_interface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "synthetic-input.mp4"
            media.write_bytes(SYNTHETIC_MP4)
            adapter = FakeVideoEnhancementAdapter(poll_states=("succeeded",))
            ledger = InMemoryEnhancementLedger()
            interface = VideoEnhancementInterface(adapter=adapter, ledger=ledger)
            request = enhancement_request(media)
            inspected = run_cli("inspect-enhancement-request", request, now=NOW, interface=interface)
            submitted = run_cli("submit-enhancement", request, now=NOW, interface=interface)
            job = {"job_id": submitted["result"]["job_id"]}
            polled = run_cli("poll-enhancement", job, now=NOW, interface=interface)
            recovered = run_cli("recover-enhancement", job, now=NOW, interface=interface)
            downloaded = run_cli("download-enhancement", job, now=NOW, interface=interface)

            cancel_request = enhancement_request(media)
            cancel_request["idempotency_key"] = "ft-05-002-cancel"
            cancel_adapter = FakeVideoEnhancementAdapter(poll_states=("running",))
            cancel_interface = VideoEnhancementInterface(adapter=cancel_adapter, ledger=InMemoryEnhancementLedger())
            cancel_submit = run_cli("submit-enhancement", cancel_request, now=NOW, interface=cancel_interface)
            cancelled = run_cli("cancel-enhancement", {"job_id": cancel_submit["result"]["job_id"]}, now=NOW, interface=cancel_interface)

        self.assertTrue(all(item["ok"] for item in (inspected, submitted, polled, recovered, downloaded, cancel_submit, cancelled)))
        self.assertEqual(downloaded["result"]["state"], "downloaded")
        self.assertEqual(cancelled["result"]["state"], "cancelled")
        self.assertEqual(adapter.network_calls, 0)
        self.assertEqual(cancel_adapter.network_calls, 0)


if __name__ == "__main__":
    unittest.main()
