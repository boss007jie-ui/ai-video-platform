from __future__ import annotations

import base64
from dataclasses import replace
from io import StringIO
import json
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from ai_video_platform.skills.product_image_panel_generation import (
    CancellationToken,
    ImagePanelError,
    ImagePanelErrorCode,
    calculate_model_profile_digest,
    generation_request_to_mapping,
    model_profile_to_mapping,
)
from ai_video_platform.skills.product_image_panel_generation.adapters import (
    ProviderInputAsset,
    ProviderInvocation,
)
from ai_video_platform.skills.product_image_panel_generation.packy_image2_adapter import (
    EDITS_ENDPOINT,
    GENERATIONS_ENDPOINT,
    PackyHttpClient,
    PackyHttpResponse,
    PackyImage2Adapter,
)
from ai_video_platform.skills.product_image_panel_generation.cli import main as cli_main

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
        b"\xff\xd8\xff\xc0\x00\x11\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
    )


class RecordingTransport:
    def __init__(self, response: PackyHttpResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post_json(self, endpoint, *, headers, payload, timeout_seconds):
        self.calls.append(
            {
                "kind": "json",
                "endpoint": endpoint,
                "headers": dict(headers),
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response

    def post_multipart(self, endpoint, *, headers, body, content_type, timeout_seconds):
        self.calls.append(
            {
                "kind": "multipart",
                "endpoint": endpoint,
                "headers": dict(headers),
                "body": body,
                "content_type": content_type,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


def _invocation(
    *,
    width: int = 1024,
    height: int = 1024,
    input_assets: tuple[ProviderInputAsset, ...] = (),
) -> ProviderInvocation:
    request = make_request(width=width, height=height)
    return ProviderInvocation(
        request_id=request.request_id,
        request_hash=request.request_hash,
        item=request.items[0],
        profile=replace(profile(), provider_id="packy-image2", model_id="gpt-image-2"),
        compiled_prompt="Synthetic Packy product panel",
        attempt=1,
        timeout_seconds=45.0,
        input_assets=input_assets,
    )


class PackyImage2AdapterTests(unittest.TestCase):
    def test_generation_posts_exact_json_contract(self) -> None:
        content = _png()
        transport = RecordingTransport(
            PackyHttpResponse(
                200,
                {"x-request-id": "packy-generation-001"},
                json.dumps(
                    {"data": [{"b64_json": base64.b64encode(content).decode("ascii")}]}
                ).encode("utf-8"),
                12,
            )
        )
        adapter = PackyImage2Adapter(api_key="synthetic-token", transport=transport)

        asset = adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(asset.content, content)
        self.assertEqual(
            transport.calls,
            [
                {
                    "kind": "json",
                    "endpoint": GENERATIONS_ENDPOINT,
                    "headers": {
                        "Authorization": "Bearer synthetic-token",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    "payload": {
                        "model": "gpt-image-2",
                        "prompt": "Synthetic Packy product panel",
                        "quality": "high",
                        "size": "1024x1024",
                        "n": 1,
                        "output_format": "png",
                        "response_format": "b64_json",
                    },
                    "timeout_seconds": 45.0,
                }
            ],
        )

    def test_single_reference_posts_multipart_edit_contract(self) -> None:
        content = _png()
        transport = RecordingTransport(
            PackyHttpResponse(
                200,
                {"x-request-id": "packy-edit-001"},
                json.dumps(
                    {"data": [{"b64_json": base64.b64encode(content).decode("ascii")}]}
                ).encode("utf-8"),
                14,
            )
        )
        adapter = PackyImage2Adapter(api_key="synthetic-token", transport=transport)
        invocation = _invocation(
            input_assets=(
                ProviderInputAsset(
                    asset_id="approved-reference",
                    media_type="image/png",
                    uri="file:///C:/approved/approved-reference.png",
                    metadata={"approval_ref": "approval-packy-001"},
                ),
            )
        )
        with patch("pathlib.Path.read_bytes", return_value=content):
            asset = adapter._generate(invocation, cancellation=CancellationToken())

        self.assertEqual(asset.content, content)
        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["kind"], "multipart")
        self.assertEqual(call["endpoint"], EDITS_ENDPOINT)
        self.assertEqual(
            call["headers"],
            {
                "Authorization": "Bearer synthetic-token",
                "Accept": "application/json",
            },
        )
        self.assertTrue(str(call["content_type"]).startswith("multipart/form-data; boundary="))
        body = call["body"]
        self.assertIsInstance(body, bytes)
        self.assertIn(b'filename="approved-reference.png"', body)
        self.assertIn(b"Content-Type: image/png", body)
        self.assertIn(b'name="input_fidelity"\r\n\r\nhigh', body)
        self.assertIn(content, body)



    def test_response_accepts_exact_jpeg_and_rejects_url_or_dimension_mismatch(self) -> None:
        jpeg = _jpeg()
        jpeg_transport = RecordingTransport(
            PackyHttpResponse(
                200,
                {},
                json.dumps(
                    {"data": [{"b64_json": base64.b64encode(jpeg).decode("ascii")}]}
                ).encode("utf-8"),
                2,
            )
        )
        jpeg_asset = PackyImage2Adapter(
            api_key="synthetic-token",
            transport=jpeg_transport,
        )._generate(_invocation(), cancellation=CancellationToken())
        self.assertEqual(jpeg_asset.content, jpeg)
        self.assertEqual(jpeg_asset.content_type, "image/jpeg")
        self.assertEqual((jpeg_asset.width, jpeg_asset.height), (1024, 1024))

        url_transport = RecordingTransport(
            PackyHttpResponse(
                200,
                {},
                b'{"data":[{"url":"https://example.invalid/result.png"}]}',
                2,
            )
        )
        with self.assertRaises(ImagePanelError):
            PackyImage2Adapter(
                api_key="synthetic-token",
                transport=url_transport,
            )._generate(_invocation(), cancellation=CancellationToken())
        self.assertEqual(len(url_transport.calls), 1)

        wrong = _png(1024, 768)
        mismatch_transport = RecordingTransport(
            PackyHttpResponse(
                200,
                {},
                json.dumps(
                    {"data": [{"b64_json": base64.b64encode(wrong).decode("ascii")}]}
                ).encode("utf-8"),
                2,
            )
        )
        with self.assertRaises(ImagePanelError):
            PackyImage2Adapter(
                api_key="synthetic-token",
                transport=mismatch_transport,
            )._generate(_invocation(), cancellation=CancellationToken())
        self.assertEqual(len(mismatch_transport.calls), 1)


    def test_http_client_endpoint_allowlist_fails_before_connection(self) -> None:
        connection_calls: list[tuple[object, ...]] = []

        def connection_factory(*args, **kwargs):
            connection_calls.append((args, kwargs))
            raise AssertionError("network connection must not be created")

        client = PackyHttpClient(connection_factory=connection_factory)
        with self.assertRaises(ImagePanelError):
            client.post_json(
                EDITS_ENDPOINT,
                headers={},
                payload={},
                timeout_seconds=5.0,
            )
        with self.assertRaises(ImagePanelError):
            client.post_multipart(
                GENERATIONS_ENDPOINT,
                headers={},
                body=b"",
                content_type="multipart/form-data; boundary=synthetic",
                timeout_seconds=5.0,
            )
        with self.assertRaises(ImagePanelError):
            client.post_json(
                GENERATIONS_ENDPOINT + "/sibling",
                headers={},
                payload={},
                timeout_seconds=5.0,
            )
        self.assertEqual(connection_calls, [])

    def test_cli_recognizes_packy_and_missing_key_fails_before_network(self) -> None:
        configured_profile = replace(
            profile(),
            provider_id="packy-image2",
            model_id="gpt-image-2",
        )
        request = rebind_request(
            make_request(),
            model_profile_digest=calculate_model_profile_digest(configured_profile),
        )
        document = {
            "request": generation_request_to_mapping(request),
            "model_profile": model_profile_to_mapping(configured_profile),
        }
        input_path = (
            Path.cwd()
            / "tests"
            / "skills"
            / "product_image_panel_generation"
            / "packy-cli-input.json"
        )
        output = StringIO()
        with (
            patch.dict(os.environ, {"PACKY_API_KEY": ""}, clear=False),
            patch(
                "ai_video_platform.skills.product_image_panel_generation.cli.assert_task_workspace",
                return_value=input_path,
            ),
            patch("pathlib.Path.read_bytes", return_value=json.dumps(document).encode("utf-8")),
            patch(
                "http.client.HTTPSConnection",
                side_effect=AssertionError("network must not be reached"),
            ) as connection,
        ):
            exit_code = cli_main(
                [
                    "inspect-generation-request",
                    "--input",
                    str(input_path),
                    "--adapter",
                    "packy-image2",
                ],
                stdout=output,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["code"], ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED.value)
        self.assertEqual(payload["error"]["field_paths"], ["PACKY_API_KEY"])
        connection.assert_not_called()

    def test_invalid_size_multiple_references_and_bad_local_files_never_call_transport(self) -> None:
        content = _png()

        invalid_size_transport = RecordingTransport(
            PackyHttpResponse(
                200,
                {},
                json.dumps(
                    {"data": [{"b64_json": base64.b64encode(content).decode("ascii")}]}
                ).encode("utf-8"),
                1,
            )
        )
        with self.assertRaises(ImagePanelError):
            PackyImage2Adapter(
                api_key="synthetic-token",
                transport=invalid_size_transport,
            )._generate(
                _invocation(width=1000, height=1024),
                cancellation=CancellationToken(),
            )
        self.assertEqual(invalid_size_transport.calls, [])

        approved = ProviderInputAsset(
            asset_id="approved-one",
            media_type="image/png",
            uri="file:///C:/approved/one.png",
            metadata={"approval_ref": "approval-packy-one"},
        )
        multiple_transport = RecordingTransport(
            PackyHttpResponse(500, {}, b"{}", 1)
        )
        with self.assertRaises(ImagePanelError):
            PackyImage2Adapter(
                api_key="synthetic-token",
                transport=multiple_transport,
            )._generate(
                _invocation(input_assets=(approved, replace(approved, asset_id="approved-two"))),
                cancellation=CancellationToken(),
            )
        self.assertEqual(multiple_transport.calls, [])

        invalid_cases = (
            (
                "non-file",
                replace(approved, uri="https://example.invalid/reference.png"),
                None,
            ),
            (
                "missing",
                approved,
                FileNotFoundError("synthetic missing"),
            ),
            (
                "unreadable",
                approved,
                PermissionError("synthetic unreadable"),
            ),
            (
                "not-image",
                approved,
                b"not-an-image",
            ),
            (
                "wrong-media",
                replace(approved, media_type="application/octet-stream"),
                None,
            ),
        )
        for label, asset, file_result in invalid_cases:
            with self.subTest(label=label):
                transport = RecordingTransport(PackyHttpResponse(500, {}, b"{}", 1))
                adapter = PackyImage2Adapter(
                    api_key="synthetic-token",
                    transport=transport,
                )
                if isinstance(file_result, BaseException):
                    boundary = patch("pathlib.Path.read_bytes", side_effect=file_result)
                else:
                    boundary = patch("pathlib.Path.read_bytes", return_value=file_result)
                with boundary, self.assertRaises(ImagePanelError):
                    adapter._generate(
                        _invocation(input_assets=(asset,)),
                        cancellation=CancellationToken(),
                    )
                self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
