from __future__ import annotations

from datetime import datetime, timezone
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_generation.offline_acceptance import main, run_acceptance
from tests.skills.video_generation.test_video_generation_interface import execution_package


NOW = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)


class VideoGenerationOfflineAcceptanceTests(unittest.TestCase):
    def test_acceptance_covers_fake_rejecting_cancel_and_recovery_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory) / "evidence"
            receipt = run_acceptance(execution_package(), evidence_dir=evidence_dir, now=NOW)
            persisted = json.loads((evidence_dir / "offline-acceptance-receipt.json").read_text(encoding="utf-8"))
            request = json.loads((evidence_dir / "sanitized-business-request.json").read_text(encoding="utf-8"))

        self.assertEqual(receipt, persisted)
        self.assertEqual(receipt["status"], "PASS")
        self.assertFalse(receipt["provider_network_performed"])
        self.assertEqual(receipt["fake_success"]["ledger_state_chain"], [
            "submitting", "submitted", "polling", "succeeded", "downloaded",
        ])
        self.assertFalse(receipt["rejecting_fail_closed"]["result"]["ok"])
        self.assertEqual(receipt["rejecting_fail_closed"]["result"]["error"]["code"], "PROVIDER_REJECTED")
        self.assertEqual(receipt["rejecting_fail_closed"]["ledger_state_chain"], ["submitting", "failed"])
        self.assertEqual(receipt["cancel_recovery"]["ledger_state_chain"], ["submitting", "submitted", "cancelled"])
        self.assertTrue(receipt["cancel_recovery"]["recovered"]["result"]["recovered"])
        self.assertEqual(receipt["poll_recovery"]["ledger_state_chain"], [
            "submitting", "submitted", "recovery_required",
        ])
        self.assertTrue(receipt["poll_recovery"]["recovered"]["result"]["recovered"])
        self.assertEqual(request["business_sample_id"], "sanitized-product-video-001")
        self.assertNotIn("KIE_API_KEY", json.dumps(request))

    def test_sensitive_package_is_rejected_before_evidence_or_stdout_leak(self) -> None:
        package = execution_package()
        secret = "synthetic-secret-value"
        package["api_key"] = secret
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = root / "package.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            evidence_dir = root / "evidence"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["--package", str(package_path), "--evidence-dir", str(evidence_dir)])

            self.assertEqual(exit_code, 2)
            self.assertFalse(evidence_dir.exists())
            self.assertNotIn(secret, stdout.getvalue())

    def test_module_cli_emits_receipt_and_rejects_existing_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = root / "package.json"
            package_path.write_text(json.dumps(execution_package()), encoding="utf-8")
            evidence_dir = root / "evidence"
            first_stdout = io.StringIO()
            with redirect_stdout(first_stdout):
                first_exit = main(["--package", str(package_path), "--evidence-dir", str(evidence_dir)])
            second_stdout = io.StringIO()
            with redirect_stdout(second_stdout):
                second_exit = main(["--package", str(package_path), "--evidence-dir", str(evidence_dir)])

        self.assertEqual(first_exit, 0)
        self.assertEqual(json.loads(first_stdout.getvalue())["status"], "PASS")
        self.assertEqual(second_exit, 2)
        self.assertEqual(json.loads(second_stdout.getvalue())["error_code"], "OFFLINE_ACCEPTANCE_REJECTED")

    def test_module_cli_network_attempt_is_blocked_with_structured_failure_receipt(self) -> None:
        def attempt_network(*args, **kwargs):
            del args, kwargs
            socket.create_connection(("example.invalid", 443))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = root / "package.json"
            package_path.write_text(json.dumps(execution_package()), encoding="utf-8")
            evidence_dir = root / "evidence"
            stdout = io.StringIO()
            with (
                patch("ai_video_platform.skills.video_generation.offline_acceptance.run_cli", side_effect=attempt_network),
                redirect_stdout(stdout),
            ):
                exit_code = main(["--package", str(package_path), "--evidence-dir", str(evidence_dir)])
            persisted = json.loads((evidence_dir / "offline-acceptance-receipt.json").read_text(encoding="utf-8"))
            emitted = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(emitted, persisted)
        self.assertEqual(persisted["error_code"], "OFFLINE_NETWORK_BLOCKED")
        self.assertFalse(persisted["provider_network_performed"])
        self.assertTrue(persisted["provider_network_attempted"])
        self.assertTrue(persisted["network_blocked"])
        self.assertFalse(persisted["checks"]["socket_network_zero"])
        self.assertNotIn("Traceback", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
