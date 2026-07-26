from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
import json
import struct
from time import perf_counter
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ai_video_platform.skills.product_image_panel_generation import (
    FakeSeedanceNzImageAdapter,
    FakeImageProviderAdapter,
    GenerationCommand,
    ImagePanelError,
    ImagePanelErrorCode,
    ImagePanelService,
    SeedanceNzImageAdapter as PublicSeedanceNzImageAdapter,
    calculate_model_profile_digest,
    calculate_request_hash,
    generation_request_to_mapping,
    model_profile_to_mapping,
)
from ai_video_platform.skills.product_image_panel_generation.cli import main as cli_main
from ai_video_platform.skills.product_image_panel_generation.seedance_nz_image_adapter import (
    FakeSeedanceNzImageAdapter as ModuleFakeSeedanceNzImageAdapter,
    SeedanceNzHttpResponse,
    SeedanceNzImageAdapter,
)

from ._support import make_request, profile, rebind_request


def _png(width: int = 1024, height: int = 1024) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def _jpeg(width: int = 1024, height: int = 1024) -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xc0"
        + (17).to_bytes(2, "big")
        + b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        + b"\xff\xd9"
    )


class SeedanceCliRecordingTransport:
    def __init__(self, responses: list[SeedanceNzHttpResponse], *, download_body: bytes) -> None:
        self.responses = list(responses)
        self.download_body = download_body
        self.calls: list[dict[str, object]] = []

    def post_json(self, endpoint, *, headers, payload, timeout_seconds):
        self.calls.append({"method": "POST", "endpoint": endpoint})
        return self.responses.pop(0)

    def get_json(self, endpoint, *, headers, timeout_seconds):
        self.calls.append({"method": "GET", "endpoint": endpoint})
        return self.responses.pop(0)

    def get_bytes(self, endpoint, *, headers, timeout_seconds):
        self.calls.append({"method": "GET_BYTES", "endpoint": endpoint})
        return self.download_body


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
            make_request(valid_until="2000-01-01T00:00:00Z"),
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

    def test_cli_inspect_recognizes_seedance_configuration_without_transport(self) -> None:
        configured_profile = replace(
            profile(), provider_id="seedance-nz-image", model_id="seedream-v5-pro-t2i"
        )
        request = rebind_request(
            make_request(),
            model_profile_digest=calculate_model_profile_digest(configured_profile),
        )
        document = {
            "request": generation_request_to_mapping(request),
            "model_profile": model_profile_to_mapping(configured_profile),
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            with patch.dict("os.environ", {"SEEDANCE_NZ_API_KEY": "sk-synthetic"}):
                exit_code = cli_main(
                    [
                        "inspect-generation-request",
                        "--input",
                        str(input_path),
                        "--adapter",
                        "seedance-nz-image",
                    ],
                    stdout=output,
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["provider_smoke"], "NOT_AUTHORIZED")

    def test_skill_root_exports_only_public_seedance_adapter_classes(self) -> None:
        import ai_video_platform.skills.product_image_panel_generation as skill_root

        self.assertIs(PublicSeedanceNzImageAdapter, SeedanceNzImageAdapter)
        self.assertIs(FakeSeedanceNzImageAdapter, ModuleFakeSeedanceNzImageAdapter)
        self.assertFalse(hasattr(skill_root, "SeedanceNzHttpClient"))
        self.assertFalse(hasattr(skill_root, "SeedanceNzHttpResponse"))

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

    def test_cli_rejects_unknown_adapter_without_loading_input(self) -> None:
        output = StringIO()

        exit_code = cli_main(
            ["generate-panel", "--input", "not-loaded.json", "--adapter", "real"],
            stdout=output,
        )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["code"], ImagePanelErrorCode.CONTRACT_INVALID.value)
        self.assertEqual(payload["error"]["field_paths"], ["argv"])

    def test_cli_recognizes_yunwu_adapters_but_requires_key_before_network(self) -> None:
        bindings = (
            ("yunwu-nano-banana", "gemini-3.1-flash-image-preview"),
            ("yunwu-image2", "gpt-image-2"),
        )
        for adapter_name, model_id in bindings:
            with self.subTest(adapter_name=adapter_name):
                configured_profile = replace(
                    profile(),
                    provider_id=adapter_name,
                    model_id=model_id,
                )
                request = rebind_request(
                    make_request(),
                    model_profile_digest=calculate_model_profile_digest(configured_profile),
                )
                document = {
                    "request": generation_request_to_mapping(request),
                    "model_profile": model_profile_to_mapping(configured_profile),
                }
                output = StringIO()
                with tempfile.TemporaryDirectory() as directory:
                    input_path = Path(directory) / "request.json"
                    input_path.write_text(json.dumps(document), encoding="utf-8")
                    with patch.dict("os.environ", {"YUNWU_API_KEY": ""}):
                        exit_code = cli_main(
                            [
                                "generate-panel",
                                "--input",
                                str(input_path),
                                "--adapter",
                                adapter_name,
                            ],
                            stdout=output,
                        )

                payload = json.loads(output.getvalue())
                self.assertEqual(exit_code, 2)
                self.assertEqual(
                    payload["error"]["code"],
                    ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED.value,
                )

    def test_cli_recognizes_seedance_adapter_but_requires_key_before_network(self) -> None:
        configured_profile = replace(
            profile(),
            provider_id="seedance-nz-image",
            model_id="seedream-v5-pro-t2i",
        )
        request = rebind_request(
            make_request(max_attempts=1),
            model_profile_digest=calculate_model_profile_digest(configured_profile),
        )
        document = {
            "request": generation_request_to_mapping(request),
            "model_profile": model_profile_to_mapping(configured_profile),
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            with patch.dict("os.environ", {"SEEDANCE_NZ_API_KEY": ""}):
                exit_code = cli_main(
                    [
                        "generate-panel",
                        "--input",
                        str(input_path),
                        "--adapter",
                        "seedance-nz-image",
                    ],
                    stdout=output,
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["code"], ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED.value)
        self.assertEqual(payload["error"]["field_paths"], ["SEEDANCE_NZ_API_KEY"])

    def test_seedance_cli_persists_artifact_receipt_and_exact_replay_is_offline(self) -> None:
        content = _png()
        signed_url = "https://cdn.seedance.nz/cli-panel.png?token=secret-signature"
        transport = SeedanceCliRecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-cli-001"}', 1),
                SeedanceNzHttpResponse(
                    200,
                    {},
                    json.dumps(
                        {
                            "code": "success",
                            "data": {"status": "SUCCESS", "result_url": signed_url},
                        }
                    ).encode(),
                    1,
                ),
            ],
            download_body=content,
        )
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic-secret", transport=transport, sleep=lambda _: None)
        configured_profile = replace(
            profile(),
            provider_id="seedance-nz-image",
            model_id="seedream-v5-pro-t2i",
            cost_per_attempt=1,
        )
        request = rebind_request(
            make_request(max_attempts=1),
            model_profile_digest=calculate_model_profile_digest(configured_profile),
            budget=replace(make_request().budget, max_attempts=1, timeout_seconds=300.0),
        )
        document = {
            "request": generation_request_to_mapping(request),
            "model_profile": model_profile_to_mapping(configured_profile),
        }
        first_output = StringIO()
        second_output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "request.json"
            output_dir = root / "output"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            with patch(
                "ai_video_platform.skills.product_image_panel_generation.cli._adapter_from_name",
                return_value=adapter,
            ):
                first_exit = cli_main(
                    [
                        "generate-panel",
                        "--input",
                        str(input_path),
                        "--adapter",
                        "seedance-nz-image",
                        "--output-dir",
                        str(output_dir),
                    ],
                    stdout=first_output,
                )
                second_exit = cli_main(
                    [
                        "generate-panel",
                        "--input",
                        str(input_path),
                        "--adapter",
                        "seedance-nz-image",
                        "--output-dir",
                        str(output_dir),
                    ],
                    stdout=second_output,
                )
            persisted = list(output_dir.glob("*.png"))

        first = json.loads(first_output.getvalue())
        second = json.loads(second_output.getvalue())
        self.assertEqual((first_exit, second_exit), (0, 0))
        self.assertEqual([call["method"] for call in transport.calls], ["POST", "GET", "GET_BYTES"])
        self.assertEqual(len(persisted), 1)
        self.assertEqual(first["provider_smoke"], "CONTROLLED_FIRST_RUN_REQUIRED")
        self.assertTrue(first["provider_network_performed"])
        self.assertEqual(first["provider_receipt"]["task_id"], "task-cli-001")
        self.assertNotIn("result_url", first["provider_receipt"])
        self.assertEqual(first["artifact_receipt"]["provider_asset_id"], "task-cli-001")
        self.assertEqual(first["artifact_receipt"]["task_id"], "task-cli-001")
        self.assertEqual(first["artifact_receipt"]["content_type"], "image/png")
        self.assertEqual(first["artifact_receipt"]["byte_size"], len(content))
        self.assertEqual(first["artifact_receipt"]["width"], 1024)
        self.assertEqual(first["artifact_receipt"]["height"], 1024)
        self.assertTrue(second["replayed"])
        self.assertEqual(first["artifact_receipt"], second["artifact_receipt"])
        self.assertNotIn("sk-synthetic-secret", first_output.getvalue())
        self.assertNotIn("secret-signature", first_output.getvalue())

    def test_seedance_cli_dimension_mismatch_writes_no_success_artifact(self) -> None:
        transport = SeedanceCliRecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-cli-size"}', 1),
                SeedanceNzHttpResponse(
                    200,
                    {},
                    b'{"data":{"status":"SUCCESS","result_url":"https://cdn.seedance.nz/wrong-size.png"}}',
                    1,
                ),
            ],
            download_body=_png(512, 512),
        )
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)
        configured_profile = replace(
            profile(), provider_id="seedance-nz-image", model_id="seedream-v5-pro-t2i", cost_per_attempt=1
        )
        request = rebind_request(
            make_request(max_attempts=1),
            model_profile_digest=calculate_model_profile_digest(configured_profile),
        )
        document = {
            "request": generation_request_to_mapping(request),
            "model_profile": model_profile_to_mapping(configured_profile),
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "request.json"
            output_dir = root / "output"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            with patch(
                "ai_video_platform.skills.product_image_panel_generation.cli._adapter_from_name",
                return_value=adapter,
            ):
                exit_code = cli_main(
                    [
                        "generate-panel",
                        "--input",
                        str(input_path),
                        "--adapter",
                        "seedance-nz-image",
                        "--output-dir",
                        str(output_dir),
                    ],
                    stdout=output,
                )
            persisted = list(output_dir.glob("*")) if output_dir.exists() else []

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 3)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(persisted, [])

    def test_seedance_cli_uses_jpg_extension_for_jpeg_content(self) -> None:
        transport = SeedanceCliRecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-cli-jpeg"}', 1),
                SeedanceNzHttpResponse(
                    200,
                    {},
                    b'{"data":{"status":"SUCCESS","result_url":"https://cdn.seedance.nz/panel.jpeg"}}',
                    1,
                ),
            ],
            download_body=_jpeg(),
        )
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)
        configured_profile = replace(
            profile(), provider_id="seedance-nz-image", model_id="seedream-v5-pro-t2i", cost_per_attempt=1
        )
        request = rebind_request(
            make_request(command=GenerationCommand.GENERATE_PRODUCT_IMAGE, max_attempts=1),
            model_profile_digest=calculate_model_profile_digest(configured_profile),
        )
        document = {
            "request": generation_request_to_mapping(request),
            "model_profile": model_profile_to_mapping(configured_profile),
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            with patch(
                "ai_video_platform.skills.product_image_panel_generation.cli._adapter_from_name",
                return_value=adapter,
            ):
                exit_code = cli_main(
                    [
                        "generate-product-image",
                        "--input",
                        str(input_path),
                        "--adapter",
                        "seedance-nz-image",
                    ],
                    stdout=output,
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["artifact_receipt"]["content_type"], "image/jpeg")
        self.assertTrue(payload["artifact_receipt"]["path"].endswith(".jpg"))

    def test_generate_panels_rejects_seedance_before_adapter_construction(self) -> None:
        document = {
            "model_profile": model_profile_to_mapping(profile()),
        }
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            with patch(
                "ai_video_platform.skills.product_image_panel_generation.cli._adapter_from_name"
            ) as adapter_factory:
                exit_code = cli_main(
                    [
                        "generate-panels",
                        "--input",
                        str(input_path),
                        "--adapter",
                        "seedance-nz-image",
                    ],
                    stdout=output,
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["code"], ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED.value)
        adapter_factory.assert_not_called()

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
