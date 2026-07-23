from __future__ import annotations

import base64
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from ai_video_platform.skills.product_image_panel_generation import (
    CancellationToken,
    ImagePanelError,
    ImagePanelErrorCode,
    ImagePanelService,
    calculate_model_profile_digest,
    generation_request_to_mapping,
    model_profile_to_mapping,
)
from ai_video_platform.skills.product_image_panel_generation.adapters import ProviderInvocation
from ai_video_platform.skills.product_image_panel_generation.cli import main as cli_main
from ai_video_platform.skills.product_image_panel_generation.yunwu_adapters import (
    IMAGE2_ENDPOINT,
    NANO_BANANA_ENDPOINT,
    YunwuHttpClient,
    YunwuHttpResponse,
    YunwuImage2Adapter,
    YunwuNanoBananaAdapter,
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


class RecordingTransport:
    def __init__(self, response: YunwuHttpResponse) -> None:
        self.response = response
        self.calls = []

    def post_json(self, endpoint, *, headers, payload, timeout_seconds):
        self.calls.append(
            {
                "endpoint": endpoint,
                "headers": dict(headers),
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


def _invocation(
    provider_id: str,
    model_id: str,
    *,
    timeout_seconds: float = 300.0,
) -> ProviderInvocation:
    request = make_request()
    return ProviderInvocation(
        request_id=request.request_id,
        request_hash=request.request_hash,
        item=request.items[0],
        profile=replace(profile(), provider_id=provider_id, model_id=model_id),
        compiled_prompt="Synthetic clean-room storyboard overview",
        attempt=1,
        timeout_seconds=timeout_seconds,
    )


class YunwuAdapterTests(unittest.TestCase):
    def test_real_cli_persists_receipt_chain_and_exact_replay_performs_no_second_call(self) -> None:
        content = _png()
        transport = RecordingTransport(
            YunwuHttpResponse(
                200,
                {"x-request-id": "image2-cli-001"},
                json.dumps(
                    {
                        "data": [{"b64_json": base64.b64encode(content).decode("ascii")}],
                        "usage": {"cost": 0.01},
                    }
                ).encode(),
                321,
            )
        )
        adapter = YunwuImage2Adapter(api_key="synthetic-key", transport=transport)
        configured_profile = replace(
            profile(),
            provider_id="yunwu-image2",
            model_id="gpt-image-2",
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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            first_output = StringIO()
            second_output = StringIO()
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
                        "yunwu-image2",
                        "--output-dir",
                        str(root),
                    ],
                    stdout=first_output,
                )
                second_exit = cli_main(
                    [
                        "generate-panel",
                        "--input",
                        str(input_path),
                        "--adapter",
                        "yunwu-image2",
                        "--output-dir",
                        str(root),
                    ],
                    stdout=second_output,
                )
            persisted = list(root.glob("*.png"))

        first = json.loads(first_output.getvalue())
        second = json.loads(second_output.getvalue())
        self.assertEqual((first_exit, second_exit), (0, 0))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(first["provider_smoke"], "PASS")
        self.assertTrue(first["provider_network_performed"])
        self.assertEqual(first["provider_receipt"]["http_status"], 200)
        self.assertEqual(first["artifact_receipt"]["byte_size"], len(content))
        self.assertEqual(first["artifact_receipt"]["width"], 1024)
        self.assertTrue(second["replayed"])
        self.assertEqual(first["artifact_receipt"], second["artifact_receipt"])

    def test_real_cli_rejects_output_directory_outside_input_workspace_before_network(self) -> None:
        configured_profile = replace(
            profile(),
            provider_id="yunwu-image2",
            model_id="gpt-image-2",
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
        with (
            tempfile.TemporaryDirectory() as input_directory,
            tempfile.TemporaryDirectory() as output_directory,
        ):
            input_path = Path(input_directory) / "request.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            with patch(
                "ai_video_platform.skills.product_image_panel_generation.cli._adapter_from_name"
            ) as adapter_factory:
                exit_code = cli_main(
                    [
                        "generate-panel",
                        "--input",
                        str(input_path),
                        "--adapter",
                        "yunwu-image2",
                        "--output-dir",
                        output_directory,
                    ],
                    stdout=output,
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["field_paths"], ["output_dir"])
        adapter_factory.assert_not_called()

    def test_service_chain_records_verified_provider_dimensions_and_http_receipt(self) -> None:
        content = _png(512, 256)
        transport = RecordingTransport(
            YunwuHttpResponse(
                200,
                {"x-request-id": "image2-service-001"},
                json.dumps(
                    {
                        "data": [{"b64_json": base64.b64encode(content).decode("ascii")}],
                        "usage": {"cost": 0.01},
                    }
                ).encode(),
                444,
            )
        )
        adapter = YunwuImage2Adapter(api_key="synthetic-key", transport=transport)
        configured_profile = replace(
            profile(),
            provider_id="yunwu-image2",
            model_id="gpt-image-2",
        )
        request = rebind_request(
            make_request(max_attempts=1),
            model_profile_digest=calculate_model_profile_digest(configured_profile),
        )
        service = ImagePanelService(provider=adapter, profiles=(configured_profile,))

        outcome = service.generate_panel(request)

        manifest_asset = outcome.asset_manifest.payload["assets"][0]
        self.assertEqual(manifest_asset["dimensions"], {"width": 512, "height": 256})
        self.assertEqual(manifest_asset["provider_metadata"]["endpoint"], IMAGE2_ENDPOINT)
        self.assertEqual(manifest_asset["provider_metadata"]["http_status"], 200)
        self.assertEqual(manifest_asset["provider_metadata"]["elapsed_ms"], 444)
        self.assertEqual(manifest_asset["provider_metadata"]["cost_fields"], {"usage": {"cost": 0.01}})

    def test_nano_banana_uses_only_signed_endpoint_model_and_minimal_payload(self) -> None:
        content = _png()
        response = {
            "responseId": "nano-response-001",
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": base64.b64encode(content).decode("ascii"),
                                }
                            }
                        ]
                    }
                }
            ],
            "usageMetadata": {"totalTokenCount": 17},
        }
        transport = RecordingTransport(
            YunwuHttpResponse(200, {}, json.dumps(response).encode("utf-8"), 1234)
        )
        adapter = YunwuNanoBananaAdapter(api_key="synthetic-key", transport=transport)

        asset = adapter._generate(
            _invocation(
                provider_id="yunwu-nano-banana",
                model_id="gemini-3.1-flash-image-preview",
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["endpoint"], NANO_BANANA_ENDPOINT)
        self.assertEqual(call["headers"]["Authorization"], "Bearer synthetic-key")
        self.assertEqual(
            call["payload"],
            {
                "contents": [
                    {"parts": [{"text": "Synthetic clean-room storyboard overview"}]}
                ],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            },
        )
        self.assertEqual(call["timeout_seconds"], 300.0)
        self.assertEqual(asset.content, content)
        self.assertEqual((asset.width, asset.height), (1024, 1024))
        self.assertEqual(asset.provider_asset_id, "nano-response-001")
        self.assertEqual(adapter.last_receipt.http_status, 200)
        self.assertEqual(
            adapter.last_receipt.cost_fields,
            {"usageMetadata": {"totalTokenCount": 17}},
        )

    def test_image2_uses_low_1024_single_generation_and_decodes_inline_bytes(self) -> None:
        content = _png()
        response = {
            "created": 1,
            "data": [{"b64_json": base64.b64encode(content).decode("ascii")}],
            "usage": {"input_tokens": 9, "output_tokens": 11},
        }
        transport = RecordingTransport(
            YunwuHttpResponse(
                200,
                {"x-request-id": "image2-request-001"},
                json.dumps(response).encode("utf-8"),
                987,
            )
        )
        adapter = YunwuImage2Adapter(api_key="synthetic-key", transport=transport)

        asset = adapter._generate(
            _invocation(provider_id="yunwu-image2", model_id="gpt-image-2"),
            cancellation=CancellationToken(),
        )

        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["endpoint"], IMAGE2_ENDPOINT)
        self.assertEqual(
            call["payload"],
            {
                "model": "gpt-image-2",
                "prompt": "Synthetic clean-room storyboard overview",
                "quality": "low",
                "size": "1024x1024",
                "n": 1,
                "output_format": "png",
            },
        )
        self.assertEqual(asset.content, content)
        self.assertEqual(asset.provider_asset_id, "image2-request-001")
        self.assertEqual(
            adapter.last_receipt.cost_fields,
            {"usage": {"input_tokens": 9, "output_tokens": 11}},
        )

    def test_image2_all_variant_is_allowed_but_other_models_fail_before_network(self) -> None:
        content = _png()
        transport = RecordingTransport(
            YunwuHttpResponse(
                200,
                {},
                json.dumps(
                    {"data": [{"b64_json": base64.b64encode(content).decode("ascii")}]}
                ).encode(),
                1,
            )
        )
        adapter = YunwuImage2Adapter(api_key="synthetic-key", transport=transport)
        adapter._generate(
            _invocation(provider_id="yunwu-image2", model_id="gpt-image-2-all"),
            cancellation=CancellationToken(),
        )
        self.assertEqual(len(transport.calls), 1)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(
                _invocation(provider_id="yunwu-image2", model_id="other-model"),
                cancellation=CancellationToken(),
            )

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED)
        self.assertEqual(len(transport.calls), 1)

    def test_nano_wrong_model_and_provider_id_fail_before_network(self) -> None:
        transport = RecordingTransport(YunwuHttpResponse(500, {}, b"{}", 1))
        adapter = YunwuNanoBananaAdapter(api_key="synthetic-key", transport=transport)
        for invocation in (
            _invocation(provider_id="yunwu-nano-banana", model_id="other-model"),
            _invocation(
                provider_id="other-provider",
                model_id="gemini-3.1-flash-image-preview",
            ),
        ):
            with self.assertRaises(ImagePanelError) as captured:
                adapter._generate(invocation, cancellation=CancellationToken())
            self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED)
        self.assertEqual(transport.calls, [])

    def test_redirect_status_fails_closed_without_retry(self) -> None:
        transport = RecordingTransport(
            YunwuHttpResponse(
                302,
                {"location": "https://example.invalid"},
                b"redirect",
                4,
            )
        )
        adapter = YunwuNanoBananaAdapter(api_key="synthetic-key", transport=transport)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(
                _invocation(
                    provider_id="yunwu-nano-banana",
                    model_id="gemini-3.1-flash-image-preview",
                ),
                cancellation=CancellationToken(),
            )

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertFalse(captured.exception.retryable)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(adapter.last_receipt.http_status, 302)
        self.assertEqual(adapter.last_receipt.error_body, "redirect")

    def test_public_generate_remains_fail_closed_for_real_adapters(self) -> None:
        adapter = YunwuImage2Adapter(
            api_key="synthetic-key",
            transport=RecordingTransport(YunwuHttpResponse(500, {}, b"", 1)),
        )

        with self.assertRaises(ImagePanelError) as captured:
            adapter.generate(None, cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_BYPASS_FORBIDDEN)

    def test_image2_url_delivery_is_rejected_without_download(self) -> None:
        transport = RecordingTransport(
            YunwuHttpResponse(
                200,
                {},
                b'{"data":[{"url":"https://example.invalid/image.png"}]}',
                2,
            )
        )
        adapter = YunwuImage2Adapter(api_key="synthetic-key", transport=transport)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(
                _invocation(provider_id="yunwu-image2", model_id="gpt-image-2"),
                cancellation=CancellationToken(),
            )

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertEqual(len(transport.calls), 1)

    def test_timeout_is_hard_capped_at_300_seconds(self) -> None:
        content = _png()
        transport = RecordingTransport(
            YunwuHttpResponse(
                200,
                {},
                json.dumps(
                    {"data": [{"b64_json": base64.b64encode(content).decode("ascii")}]}
                ).encode(),
                1,
            )
        )
        adapter = YunwuImage2Adapter(api_key="synthetic-key", transport=transport)

        adapter._generate(
            _invocation(
                provider_id="yunwu-image2",
                model_id="gpt-image-2",
                timeout_seconds=900,
            ),
            cancellation=CancellationToken(),
        )

        self.assertEqual(transport.calls[0]["timeout_seconds"], 300.0)

    def test_empty_key_is_rejected_without_network(self) -> None:
        with self.assertRaisesRegex(ValueError, "YUNWU_API_KEY"):
            YunwuNanoBananaAdapter(api_key="")

    def test_http_client_rejects_every_non_allowlisted_endpoint_before_connection(self) -> None:
        called = []
        client = YunwuHttpClient(
            connection_factory=lambda *args, **kwargs: called.append((args, kwargs))
        )

        with self.assertRaises(ImagePanelError) as captured:
            client.post_json(
                "https://example.invalid/v1/images/generations",
                headers={},
                payload={},
                timeout_seconds=1,
            )

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED)
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
