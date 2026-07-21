from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
import json
from time import perf_counter
import tempfile
import unittest
from pathlib import Path

from ai_video_platform.skills.product_image_panel_generation import (
    FakeImageProviderAdapter,
    ImagePanelError,
    ImagePanelErrorCode,
    ImagePanelService,
    calculate_model_profile_digest,
    calculate_request_hash,
    generation_request_to_mapping,
    model_profile_to_mapping,
)
from ai_video_platform.skills.product_image_panel_generation.cli import main as cli_main

from ._support import make_request, profile, rebind_request


class ImagePanelInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ImagePanelService(
            provider=FakeImageProviderAdapter(),
            profiles=(profile(),),
            now=lambda: datetime(2026, 7, 20, 10, 1, tzinfo=timezone.utc),
        )

    def assert_error(self, expected: ImagePanelErrorCode, request) -> ImagePanelError:
        with self.assertRaises(ImagePanelError) as captured:
            self.service.inspect_generation_request(request)
        self.assertEqual(captured.exception.code, expected)
        return captured.exception

    def test_inspect_accepts_approved_contract_bound_request(self) -> None:
        request = make_request()

        inspection = self.service.inspect_generation_request(request)

        self.assertTrue(inspection.approved)
        self.assertEqual(inspection.request_hash, request.request_hash)
        self.assertEqual(inspection.estimated_max_cost_units, 6)
        self.assertEqual(inspection.item_count, 1)
        self.assertEqual(inspection.profile_id, "offline-image-v1")

    def test_request_hash_is_stable_and_excludes_approval_record(self) -> None:
        request = make_request()

        first = calculate_request_hash(request)
        changed_approval = replace(request, approval_record=None)

        self.assertEqual(first, calculate_request_hash(changed_approval))
        self.assertEqual(first, request.request_hash)

    def test_request_hash_mismatch_fails_closed(self) -> None:
        self.assert_error(
            ImagePanelErrorCode.REQUEST_HASH_MISMATCH,
            make_request(request_hash_override="sha256:" + "f" * 64),
        )

    def test_product_identity_mismatch_fails_closed(self) -> None:
        self.assert_error(
            ImagePanelErrorCode.PRODUCT_IDENTITY_MISMATCH,
            make_request(context_product_id="other-product"),
        )

    def test_missing_approved_input_asset_fails_closed(self) -> None:
        self.assert_error(
            ImagePanelErrorCode.ASSET_NOT_APPROVED,
            make_request(approved_assets=()),
        )

    def test_missing_budget_fails_closed(self) -> None:
        request = replace(make_request(), budget=None)
        self.assert_error(ImagePanelErrorCode.BUDGET_REQUIRED, request)

    def test_budget_below_worst_case_retry_cost_fails_closed(self) -> None:
        self.assert_error(
            ImagePanelErrorCode.BUDGET_EXCEEDED,
            make_request(max_cost_units=5, max_attempts=2),
        )

    def test_invalid_dimensions_fail_closed(self) -> None:
        self.assert_error(
            ImagePanelErrorCode.DIMENSIONS_INVALID,
            make_request(width=1023),
        )

    def test_stale_task_context_fails_closed(self) -> None:
        self.assert_error(
            ImagePanelErrorCode.STALE_INPUT,
            make_request(context_revision=3, expected_context_revision=4),
        )

    def test_ineffective_approval_fails_closed(self) -> None:
        self.assert_error(
            ImagePanelErrorCode.APPROVAL_NOT_EFFECTIVE,
            make_request(approval_outcome="denied"),
        )

    def test_expired_approval_fails_closed(self) -> None:
        self.assert_error(
            ImagePanelErrorCode.APPROVAL_NOT_EFFECTIVE,
            make_request(valid_until="2026-07-20T09:59:59Z"),
        )

    def test_wrong_active_skill_fails_closed(self) -> None:
        self.assert_error(
            ImagePanelErrorCode.SKILL_BINDING_INVALID,
            make_request(active_skill_id="storyboard"),
        )

    def test_approved_request_binds_full_model_profile_configuration(self) -> None:
        request = make_request()
        changed_profile = replace(profile(), model_id="changed-after-approval")
        service = ImagePanelService(
            provider=FakeImageProviderAdapter(),
            profiles=(changed_profile,),
            now=lambda: datetime(2026, 7, 20, 10, 1, tzinfo=timezone.utc),
        )

        with self.assertRaises(ImagePanelError) as captured:
            service.inspect_generation_request(request)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.MODEL_PROFILE_INVALID)

    def test_non_positive_model_cost_and_dimension_multiple_fail_closed(self) -> None:
        for changed_profile in (
            replace(profile(), cost_per_attempt=-1),
            replace(profile(), dimension_multiple=0),
        ):
            with self.subTest(profile=changed_profile):
                request = rebind_request(
                    make_request(),
                    model_profile_digest=calculate_model_profile_digest(changed_profile),
                )
                service = ImagePanelService(
                    provider=FakeImageProviderAdapter(),
                    profiles=(changed_profile,),
                    now=lambda: datetime(2026, 7, 20, 10, 1, tzinfo=timezone.utc),
                )

                with self.assertRaises(ImagePanelError) as captured:
                    service.inspect_generation_request(request)

                self.assertEqual(captured.exception.code, ImagePanelErrorCode.MODEL_PROFILE_INVALID)

    def test_cli_inspect_returns_machine_readable_preflight(self) -> None:
        request = make_request()
        document = {
            "request": generation_request_to_mapping(request),
            "model_profile": model_profile_to_mapping(profile()),
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            exit_code = cli_main(
                ["inspect-generation-request", "--input", str(input_path)],
                stdout=output,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["request_hash"], request.request_hash)

    def test_cli_fake_panel_generation_is_explicit_and_offline(self) -> None:
        document = {
            "request": generation_request_to_mapping(make_request()),
            "model_profile": model_profile_to_mapping(profile()),
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            exit_code = cli_main(
                ["generate-panel", "--input", str(input_path), "--adapter", "fake"],
                stdout=output,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["provider_smoke"], "NOT_AUTHORIZED")

    def test_cli_exact_replay_uses_task_workspace_ledger_across_invocations(self) -> None:
        request = make_request()
        document = {
            "request": generation_request_to_mapping(request),
            "model_profile": model_profile_to_mapping(profile()),
        }
        first_output = StringIO()
        second_output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            first_exit = cli_main(
                ["generate-panel", "--input", str(input_path), "--adapter", "fake"],
                stdout=first_output,
            )
            second_exit = cli_main(
                ["generate-panel", "--input", str(input_path), "--adapter", "fake"],
                stdout=second_output,
            )

        first = json.loads(first_output.getvalue())
        second = json.loads(second_output.getvalue())
        self.assertEqual((first_exit, second_exit), (0, 0))
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(first["asset_manifest"]["contract_id"], second["asset_manifest"]["contract_id"])

    def test_cli_ledger_rejects_same_key_with_different_request_hash(self) -> None:
        original = make_request()
        changed = rebind_request(
            original,
            items=(replace(original.items[0], prompt="A materially different panel"),),
        )
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "request.json"
            input_path.write_text(
                json.dumps(
                    {
                        "request": generation_request_to_mapping(original),
                        "model_profile": model_profile_to_mapping(profile()),
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                cli_main(
                    ["generate-panel", "--input", str(input_path), "--adapter", "fake"],
                    stdout=StringIO(),
                ),
                0,
            )
            input_path.write_text(
                json.dumps(
                    {
                        "request": generation_request_to_mapping(changed),
                        "model_profile": model_profile_to_mapping(profile()),
                    }
                ),
                encoding="utf-8",
            )
            exit_code = cli_main(
                ["generate-panel", "--input", str(input_path), "--adapter", "fake"],
                stdout=output,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["code"], ImagePanelErrorCode.IDEMPOTENCY_CONFLICT.value)

    def test_cli_defaults_to_rejecting_adapter(self) -> None:
        rejecting_profile = replace(profile(), provider_id="rejecting")
        request = rebind_request(
            make_request(),
            model_profile_digest=calculate_model_profile_digest(rejecting_profile),
        )
        document = {
            "request": generation_request_to_mapping(request),
            "model_profile": model_profile_to_mapping(rejecting_profile),
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            exit_code = cli_main(["generate-panel", "--input", str(input_path)], stdout=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 3)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(
            payload["generation_record"]["items"][0]["error"]["code"],
            ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED.value,
        )

    def test_cli_malformed_input_uses_stable_sanitized_error_and_exit_two(self) -> None:
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "request.json"
            input_path.write_text('{"request":', encoding="utf-8")

            exit_code = cli_main(
                ["inspect-generation-request", "--input", str(input_path)],
                stdout=output,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["code"], ImagePanelErrorCode.CONTRACT_INVALID.value)
        self.assertNotIn("Traceback", output.getvalue())

    def test_two_hundred_preflights_complete_within_one_second(self) -> None:
        request = make_request()

        started = perf_counter()
        for _ in range(200):
            self.service.inspect_generation_request(request)
        elapsed = perf_counter() - started

        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
