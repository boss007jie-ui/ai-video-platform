from __future__ import annotations

from datetime import datetime, timezone
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_enhancement.offline_acceptance import main, run_acceptance


NOW = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)


class VideoEnhancementOfflineAcceptanceTests(unittest.TestCase):
    def test_acceptance_exercises_fake_rejecting_cancel_and_recovery_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            receipt = run_acceptance(evidence_dir=evidence, now=NOW)
            persisted = json.loads((evidence / "offline-acceptance-receipt.json").read_text(encoding="utf-8"))
            sample = json.loads((evidence / "sanitized-business-sample.json").read_text(encoding="utf-8"))

        self.assertEqual(receipt, persisted)
        self.assertEqual(receipt["status"], "PASS")
        self.assertFalse(receipt["provider_network_performed"])
        self.assertEqual(receipt["fake_success"]["ledger_state_chain"], [
            "submitting", "submitted", "polling", "succeeded", "downloaded",
        ])
        self.assertEqual(receipt["rejecting_fail_closed"]["ledger_state_chain"], ["submitting", "failed"])
        self.assertEqual(receipt["cancel_recovery"]["ledger_state_chain"], ["submitting", "submitted", "cancelled"])
        self.assertEqual(receipt["poll_recovery"]["ledger_state_chain"], ["submitting", "submitted", "recovery_required"])
        self.assertEqual(sample["business_sample_id"], "sanitized-video-enhancement-001")
        self.assertNotIn("path", json.dumps(sample))

    def test_cli_writes_receipt_and_refuses_to_overwrite_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            first_output = io.StringIO()
            with redirect_stdout(first_output):
                first = main(["--evidence-dir", str(evidence)])
            second_output = io.StringIO()
            with redirect_stdout(second_output):
                second = main(["--evidence-dir", str(evidence)])

        self.assertEqual(first, 0)
        self.assertEqual(json.loads(first_output.getvalue())["status"], "PASS")
        self.assertEqual(second, 2)
        self.assertEqual(json.loads(second_output.getvalue())["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
