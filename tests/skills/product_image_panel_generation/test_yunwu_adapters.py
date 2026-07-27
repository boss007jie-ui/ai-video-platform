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

from ai_video_platform.contracts.serialization import thaw_json
from ai_video_platform.skills.product_image_panel_generation import (
    CancellationToken,
    FakeImageProviderAdapter,
    ImagePanelError,
    ImagePanelErrorCode,
    ImagePanelService,
    calculate_model_profile_digest,
    generation_request_to_mapping,
    model_profile_to_mapping,
)
from ai_video_platform.skills.product_image_panel_generation.adapters import (
    ProviderInputAsset,
    ProviderInvocation,
)
from ai_video_platform.skills.product_image_panel_generation.cli import main as cli_main
from ai_video_platform.skills.product_image_panel_generation.yunwu_adapters import (
    IMAGE2_ENDPOINT,
    NANO_BANANA_ENDPOINT,
    YunwuHttpClient,
    YunwuHttpResponse,
    YunwuImage2Adapter,
    YunwuNanoBananaAdapter,
)

from ._support import NOW_TEXT, _envelope, make_request, profile, rebind_request


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
    input_assets: tuple[ProviderInputAsset, ...] = (),
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
        input_assets=input_assets,
    )


class YunwuAdapterTests(unittest.TestCase):
    def test_service_resolves_item_input_assets_in_declared_order_with_metadata(self) -> None:
        asset_ids = ("asset-third", "asset-audio", "asset-first")
        request = make_request(
            approved_assets=asset_ids,
            input_asset_ids=asset_ids,
            max_attempts=1,
        )
        manifest_payload = thaw_json(request.input_asset_manifests[0].payload)
        manifest_payload["assets"] = [
            {
                "asset_id": "asset-first",
                "role": "product-reference",
                "media_type": "image/png",
                "uri": "file:///C:/synthetic/first.png",
                "sha256": "1" * 64,
                "byte_size": 101,
                "provenance": {"source": "first"},
                "created_at": NOW_TEXT,
                "approval_ref": "approval-first",
            },
            {
                "asset_id": "asset-audio",
                "role": "audio-reference",
                "media_type": "audio/mpeg",
                "uri": "file:///C:/synthetic/audio.mp3",
                "sha256": "2" * 64,
                "byte_size": 202,
                "provenance": {"source": "audio"},
                "created_at": NOW_TEXT,
                "approval_ref": "approval-audio",
            },
            {
                "asset_id": "asset-third",
                "role": "style-reference",
                "media_type": "image/jpeg",
                "uri": "file:///C:/synthetic/third.jpg",
                "sha256": "3" * 64,
                "byte_size": 303,
                "provenance": {"source": "third"},
                "created_at": NOW_TEXT,
                "approval_ref": "approval-third",
            },
        ]
        manifest = _envelope(
            "avp.contract.asset-manifest",
            manifest_payload,
            "product-knowledge",
            "skill",
        )
        request = rebind_request(request, input_asset_manifests=(manifest,))
        provider = FakeImageProviderAdapter()
        service = ImagePanelService(provider=provider, profiles=(profile(),))

        service.generate_panel(request)

        resolved = provider.invocations[0].input_assets
        self.assertEqual(tuple(asset.asset_id for asset in resolved), asset_ids)
        self.assertEqual(
            tuple(asset.media_type for asset in resolved),
            ("image/jpeg", "audio/mpeg", "image/png"),
        )
        self.assertEqual(resolved[0].metadata["sha256"], "3" * 64)
        self.assertEqual(resolved[1].metadata["provenance"], {"source": "audio"})

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
        content = _png()
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
        self.assertEqual(manifest_asset["dimensions"], {"width": 1024, "height": 1024})
        self.assertEqual(manifest_asset["provider_metadata"]["endpoint"], IMAGE2_ENDPOINT)
        self.assertEqual(manifest_asset["provider_metadata"]["http_status"], 200)
        self.assertEqual(manifest_asset["provider_metadata"]["elapsed_ms"], 444)
        self.assertEqual(manifest_asset["provider_metadata"]["cost_fields"], {"usage": {"cost": 0.01}})
        self.assertNotIn("details", manifest_asset["provider_metadata"])

    def test_provider_size_mismatch_fails_closed_with_requested_and_actual_dimensions(self) -> None:
        content = _png(512, 256)
        transport = RecordingTransport(
            YunwuHttpResponse(
                200,
                {},
                json.dumps(
                    {"data": [{"b64_json": base64.b64encode(content).decode("ascii")}]}
                ).encode(),
                444,
            )
        )
        adapter = YunwuImage2Adapter(api_key="synthetic-key", transport=transport)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(
                _invocation(
                    provider_id="yunwu-image2",
                    model_id="gpt-image-2",
                ),
                cancellation=CancellationToken(),
            )

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertFalse(captured.exception.retryable)
        self.assertEqual(
            captured.exception.message,
            "Provider image dimensions did not match requested dimensions",
        )
        self.assertEqual(
            captured.exception.details,
            {
                "requested_width": 1024,
                "requested_height": 1024,
                "actual_width": 512,
                "actual_height": 256,
            },
        )
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(adapter.last_receipt.http_status, 200)
        self.assertEqual(
            (adapter.last_receipt.width, adapter.last_receipt.height),
            (512, 256),
        )

    def test_nano_banana_embeds_ordered_local_images_and_records_skipped_non_images(self) -> None:
        content = _png()
        response = {
            "responseId": "nano-multi-001",
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
        }
        transport = RecordingTransport(
            YunwuHttpResponse(200, {}, json.dumps(response).encode("utf-8"), 9)
        )
        adapter = YunwuNanoBananaAdapter(api_key="synthetic-key", transport=transport)
        image_contents = (
            _png(),
            b"\xff\xd8\xff\xe0synthetic-jpeg",
            b"RIFF\x08\x00\x00\x00WEBPsynthetic-webp",
        )

        input_assets = (
            ProviderInputAsset("ref-png", "image", "file:///C:/synthetic/first.png"),
            ProviderInputAsset("ref-audio", "audio/mpeg", "file:///C:/synthetic/missing.mp3"),
            ProviderInputAsset("ref-jpeg", "image/jpeg", "file:///C:/synthetic/second.jpg"),
            ProviderInputAsset("ref-webp", "image/webp", "file:///C:/synthetic/third.webp"),
        )

        with patch.object(Path, "read_bytes", side_effect=image_contents) as read_bytes:
            adapter._generate(
                _invocation(
                    provider_id="yunwu-nano-banana",
                    model_id="gemini-3.1-flash-image-preview",
                    input_assets=input_assets,
                ),
                cancellation=CancellationToken(),
            )

        self.assertEqual(read_bytes.call_count, 3)

        parts = transport.calls[0]["payload"]["contents"][0]["parts"]
        self.assertEqual(parts[0], {"text": "Synthetic clean-room storyboard overview"})
        self.assertEqual(
            [part["inline_data"]["mime_type"] for part in parts[1:]],
            ["image/png", "image/jpeg", "image/webp"],
        )
        self.assertEqual(
            [part["inline_data"]["data"] for part in parts[1:]],
            [base64.b64encode(value).decode("ascii") for value in image_contents],
        )
        self.assertEqual(
            adapter.last_receipt.details,
            {"skipped_input_asset_ids": ["ref-audio"]},
        )

    def test_nano_banana_rejects_more_than_nine_images_before_file_or_transport(self) -> None:
        transport = RecordingTransport(YunwuHttpResponse(500, {}, b"{}", 1))
        adapter = YunwuNanoBananaAdapter(api_key="synthetic-key", transport=transport)
        input_assets = tuple(
            ProviderInputAsset(
                f"ref-{index}",
                "image",
                f"file:///C:/synthetic/ref-{index}.png",
            )
            for index in range(10)
        )

        with (
            patch.object(Path, "read_bytes") as read_bytes,
            self.assertRaises(ImagePanelError) as captured,
        ):
            adapter._generate(
                _invocation(
                    provider_id="yunwu-nano-banana",
                    model_id="gemini-3.1-flash-image-preview",
                    input_assets=input_assets,
                ),
                cancellation=CancellationToken(),
            )

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertEqual(
            captured.exception.message,
            "Input image count exceeded the authorized limit",
        )
        self.assertEqual(
            captured.exception.details,
            {"image_count": 10, "max_image_count": 9},
        )
        read_bytes.assert_not_called()
        self.assertEqual(transport.calls, [])

    def test_nano_banana_rejects_input_image_over_ten_mib_before_transport(self) -> None:
        transport = RecordingTransport(YunwuHttpResponse(500, {}, b"{}", 1))
        adapter = YunwuNanoBananaAdapter(api_key="synthetic-key", transport=transport)
        actual_byte_size = 10 * 1024 * 1024 + 1
        oversized = b"\x89PNG\r\n\x1a\n" + b"x" * (actual_byte_size - 8)
        input_asset = ProviderInputAsset(
            "ref-oversized",
            "image/png",
            "file:///C:/synthetic/oversized.png",
        )

        with (
            patch.object(Path, "read_bytes", return_value=oversized),
            self.assertRaises(ImagePanelError) as captured,
        ):
            adapter._generate(
                _invocation(
                    provider_id="yunwu-nano-banana",
                    model_id="gemini-3.1-flash-image-preview",
                    input_assets=(input_asset,),
                ),
                cancellation=CancellationToken(),
            )

        self.assertEqual(
            captured.exception.message,
            "Input image bytes exceeded the authorized size limit",
        )
        self.assertEqual(
            captured.exception.details,
            {
                "asset_id": "ref-oversized",
                "reason": "image_too_large",
                "actual_byte_size": actual_byte_size,
                "max_byte_size": 10 * 1024 * 1024,
            },
        )
        self.assertEqual(transport.calls, [])

    def test_nano_banana_rejects_request_body_over_eighteen_mib_before_transport(self) -> None:
        transport = RecordingTransport(YunwuHttpResponse(500, {}, b"{}", 1))
        adapter = YunwuNanoBananaAdapter(api_key="synthetic-key", transport=transport)
        image = b"\x89PNG\r\n\x1a\n" + b"x" * (7 * 1024 * 1024 - 8)
        encoded = base64.b64encode(image).decode("ascii")
        input_assets = (
            ProviderInputAsset("ref-one", "image/png", "file:///C:/synthetic/one.png"),
            ProviderInputAsset("ref-two", "image/png", "file:///C:/synthetic/two.png"),
        )
        expected_payload = {
            "contents": [
                {
                    "parts": [
                        {"text": "Synthetic clean-room storyboard overview"},
                        {"inline_data": {"mime_type": "image/png", "data": encoded}},
                        {"inline_data": {"mime_type": "image/png", "data": encoded}},
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        actual_byte_size = len(
            json.dumps(
                expected_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )

        with (
            patch.object(Path, "read_bytes", return_value=image),
            self.assertRaises(ImagePanelError) as captured,
        ):
            adapter._generate(
                _invocation(
                    provider_id="yunwu-nano-banana",
                    model_id="gemini-3.1-flash-image-preview",
                    input_assets=input_assets,
                ),
                cancellation=CancellationToken(),
            )

        self.assertGreater(actual_byte_size, 18 * 1024 * 1024)
        self.assertEqual(
            captured.exception.message,
            "Nano Banana request body exceeded the authorized size limit",
        )
        self.assertEqual(
            captured.exception.details,
            {
                "reason": "request_body_too_large",
                "actual_byte_size": actual_byte_size,
                "max_byte_size": 18 * 1024 * 1024,
            },
        )
        self.assertEqual(transport.calls, [])

    def test_nano_banana_rejects_unsafe_or_unreadable_local_image_inputs(self) -> None:
        cases = (
            (
                "invalid-scheme",
                "https://user:secret@example.invalid/image.png?token=secret",
                _png(),
                "invalid_file_uri",
            ),
            (
                "network-share",
                "file://server/share/image.png",
                _png(),
                "non_local_file_uri",
            ),
            (
                "missing",
                "file:///C:/synthetic/missing.png",
                FileNotFoundError("synthetic"),
                "file_missing",
            ),
            (
                "unreadable",
                "file:///C:/synthetic/unreadable.png",
                PermissionError("synthetic"),
                "file_unreadable",
            ),
            (
                "unsupported",
                "file:///C:/synthetic/unsupported.gif",
                b"GIF89a",
                "unsupported_image_format",
            ),
            (
                "bad-escape",
                "file:///C:/synthetic/bad%ZZ.png",
                _png(),
                "invalid_file_uri",
            ),
        )
        for asset_id, uri, read_result, expected_reason in cases:
            with self.subTest(asset_id=asset_id):
                transport = RecordingTransport(YunwuHttpResponse(500, {}, b"{}", 1))
                adapter = YunwuNanoBananaAdapter(
                    api_key="synthetic-key",
                    transport=transport,
                )
                read_options = (
                    {"side_effect": read_result}
                    if isinstance(read_result, BaseException)
                    else {"return_value": read_result}
                )
                with (
                    patch.object(Path, "read_bytes", **read_options),
                    self.assertRaises(ImagePanelError) as captured,
                ):
                    adapter._generate(
                        _invocation(
                            provider_id="yunwu-nano-banana",
                            model_id="gemini-3.1-flash-image-preview",
                            input_assets=(
                                ProviderInputAsset(asset_id, "image", uri),
                            ),
                        ),
                        cancellation=CancellationToken(),
                    )

                self.assertEqual(captured.exception.details["asset_id"], asset_id)
                self.assertEqual(captured.exception.details["reason"], expected_reason)
                self.assertNotIn("secret", json.dumps(dict(captured.exception.details)))
                self.assertEqual(transport.calls, [])

    def test_nano_banana_service_exact_replay_performs_no_second_provider_call(self) -> None:
        content = _png()
        response = {
            "responseId": "nano-replay-001",
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
        }
        transport = RecordingTransport(
            YunwuHttpResponse(200, {}, json.dumps(response).encode("utf-8"), 7)
        )
        adapter = YunwuNanoBananaAdapter(api_key="synthetic-key", transport=transport)
        configured_profile = replace(
            profile(),
            provider_id="yunwu-nano-banana",
            model_id="gemini-3.1-flash-image-preview",
        )
        request = make_request(max_attempts=1)
        manifest_payload = thaw_json(request.input_asset_manifests[0].payload)
        manifest_payload["assets"][0]["media_type"] = "image/png"
        manifest_payload["assets"][0]["uri"] = "file:///C:/synthetic/replay.png"
        manifest = _envelope(
            "avp.contract.asset-manifest",
            manifest_payload,
            "product-knowledge",
            "skill",
        )
        request = rebind_request(
            request,
            input_asset_manifests=(manifest,),
            model_profile_digest=calculate_model_profile_digest(configured_profile),
        )
        service = ImagePanelService(provider=adapter, profiles=(configured_profile,))

        with patch.object(Path, "read_bytes", return_value=content) as read_bytes:
            first = service.generate_panel(request)
            second = service.generate_panel(request)

        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(read_bytes.call_count, 1)
        self.assertEqual(len(transport.calls), 1)

    def test_nano_banana_reads_a_real_local_reference_file(self) -> None:
        content = _png()
        response = {
            "responseId": "nano-real-file-001",
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
        }
        transport = RecordingTransport(
            YunwuHttpResponse(200, {}, json.dumps(response).encode("utf-8"), 5)
        )
        adapter = YunwuNanoBananaAdapter(api_key="synthetic-key", transport=transport)

        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            reference.write_bytes(content)
            adapter._generate(
                _invocation(
                    provider_id="yunwu-nano-banana",
                    model_id="gemini-3.1-flash-image-preview",
                    input_assets=(
                        ProviderInputAsset(
                            "ref-real-file",
                            "image/png",
                            reference.as_uri(),
                        ),
                    ),
                ),
                cancellation=CancellationToken(),
            )

        parts = transport.calls[0]["payload"]["contents"][0]["parts"]
        self.assertEqual(
            parts[1],
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(content).decode("ascii"),
                }
            },
        )

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
