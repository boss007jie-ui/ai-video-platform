from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ai_video_platform.core.guards import (
    LegacyPathGuard,
    NetworkDenyGuard,
    RejectingProviderAdapter,
    SecretScanner,
)
from ai_video_platform.contracts.errors import ContractError, ErrorCategory, ErrorCode


class OfflineGuardTests(unittest.TestCase):
    def test_network_guard_blocks_socket_connections(self) -> None:
        with NetworkDenyGuard():
            with self.assertRaises(ContractError) as captured:
                socket.create_connection(("example.invalid", 443), timeout=0.01)

        self.assertEqual(captured.exception.code, ErrorCode.NETWORK_ACCESS_FORBIDDEN)

    def test_network_guard_blocks_existing_socket_send_paths(self) -> None:
        connection = socket.socket()
        self.addCleanup(connection.close)

        with NetworkDenyGuard():
            for method_name in ("send", "sendall"):
                with self.subTest(method_name=method_name):
                    with self.assertRaises(ContractError) as captured:
                        getattr(connection, method_name)(b"synthetic")

                    self.assertEqual(captured.exception.code, ErrorCode.NETWORK_ACCESS_FORBIDDEN)

    def test_network_guard_blocks_subprocess_escape(self) -> None:
        with NetworkDenyGuard():
            with self.assertRaises(ContractError) as captured:
                subprocess.run([sys.executable, "-c", "print('synthetic')"], check=True)

        self.assertEqual(captured.exception.code, ErrorCode.NETWORK_ACCESS_FORBIDDEN)

    def test_legacy_path_guard_blocks_all_six_sources_by_root(self) -> None:
        legacy_root = Path.home() / "Desktop" / ("04-" + "视频")
        guard = LegacyPathGuard()

        with self.assertRaises(ContractError) as captured:
            guard.assert_allowed(legacy_root / "veo3.1" / "README.md")

        self.assertEqual(captured.exception.code, ErrorCode.LEGACY_PATH_ACCESS_FORBIDDEN)

    def test_secret_scanner_detects_synthetic_token_without_logging_it(self) -> None:
        scanner = SecretScanner()
        synthetic = "sk" + "-" + "testonly" + "A" * 28

        findings = scanner.scan_text(synthetic, source="memory")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].source, "memory")
        self.assertNotIn(synthetic, findings[0].summary)

    def test_public_error_details_are_deeply_snapshotted_and_redacted(self) -> None:
        synthetic = "sk" + "-" + "testonly" + "A" * 28
        details = {"authorization": synthetic, "nested": {"safe": "visible"}}
        error = ContractError(
            ErrorCode.CONTRACT_VALIDATION_FAILED,
            ErrorCategory.VALIDATION,
            "Synthetic error",
            details=details,
        )
        details["nested"]["safe"] = "changed"

        serialized = error.to_dict()
        self.assertEqual(serialized["details"]["authorization"], "[REDACTED]")
        self.assertEqual(serialized["details"]["nested"]["safe"], "visible")
        self.assertNotIn(synthetic, str(serialized))

    def test_rejecting_provider_fails_closed_without_network(self) -> None:
        adapter = RejectingProviderAdapter()

        with self.assertRaises(ContractError) as captured:
            adapter.submit({"synthetic": True})

        self.assertEqual(captured.exception.code, ErrorCode.NETWORK_ACCESS_FORBIDDEN)
        self.assertEqual(adapter.attempt_count, 1)


if __name__ == "__main__":
    unittest.main()
