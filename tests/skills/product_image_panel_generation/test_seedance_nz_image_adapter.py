from __future__ import annotations

import base64
from dataclasses import replace
import json
import struct
import unittest

from ai_video_platform.skills.product_image_panel_generation import (
    CancellationToken,
    ImagePanelError,
    ImagePanelErrorCode,
)
from ai_video_platform.skills.product_image_panel_generation.adapters import ProviderInvocation
from ai_video_platform.skills.product_image_panel_generation.seedance_nz_image_adapter import (
    SEEDANCE_NZ_IMAGE_SUBMIT_ENDPOINT,
    SEEDANCE_NZ_IMAGE_TASK_ENDPOINT,
    FakeSeedanceNzImageAdapter,
    SeedanceNzHttpResponse,
    SeedanceNzImageAdapter,
    SeedanceNzHttpClient,
)

from ._support import make_request, profile


def _png(width: int = 1024, height: int = 1024) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


class RecordingTransport:
    def __init__(
        self,
        responses: list[SeedanceNzHttpResponse],
        download_body: bytes = b"",
        download_error: ImagePanelError | None = None,
    ) -> None:
        self.responses = list(responses)
        self.download_body = download_body
        self.download_error = download_error
        self.calls: list[dict[str, object]] = []

    def post_json(self, endpoint, *, headers, payload, timeout_seconds):
        self.calls.append({"method": "POST", "endpoint": endpoint, "headers": dict(headers), "payload": payload})
        return self.responses.pop(0)

    def get_json(self, endpoint, *, headers, timeout_seconds):
        self.calls.append({"method": "GET", "endpoint": endpoint, "headers": dict(headers)})
        return self.responses.pop(0)

    def get_bytes(self, endpoint, *, headers, timeout_seconds):
        self.calls.append({"method": "GET_BYTES", "endpoint": endpoint, "headers": dict(headers)})
        if self.download_error is not None:
            raise self.download_error
        return self.download_body


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _invocation(
    *,
    model_id: str = "seedream-v5-pro-t2i",
    timeout_seconds: float = 5.0,
) -> ProviderInvocation:
    request = make_request()
    return ProviderInvocation(
        request_id=request.request_id,
        request_hash=request.request_hash,
        item=request.items[0],
        profile=replace(profile(), provider_id="seedance-nz-image", model_id=model_id),
        compiled_prompt="Synthetic Seedance product panel",
        attempt=1,
        timeout_seconds=timeout_seconds,
    )


class SeedanceNzImageAdapterTests(unittest.TestCase):
    def test_production_poll_interval_uses_four_seconds_with_injected_clock(self) -> None:
        clock = FakeClock()
        transport = RecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-clock-001"}', 1),
                SeedanceNzHttpResponse(200, {}, b'{"status":"IN_PROGRESS"}', 1),
                SeedanceNzHttpResponse(
                    200,
                    {},
                    b'{"status":"SUCCESS","data":{"result_url":"https://cdn.seedance.nz/clock-001.png"}}',
                    1,
                ),
            ],
            download_body=_png(),
        )
        adapter = SeedanceNzImageAdapter(
            api_key="sk-synthetic",
            transport=transport,
            sleep=clock.sleep,
            clock=clock,
        )

        adapter._generate(_invocation(timeout_seconds=300.0), cancellation=CancellationToken())

        self.assertEqual(clock.sleeps, [4.0])

    def test_deadline_allows_long_running_task_before_success(self) -> None:
        clock = FakeClock()
        progress_responses = [
            SeedanceNzHttpResponse(200, {}, b'{"status":"IN_PROGRESS"}', 1)
            for _ in range(70)
        ]
        transport = RecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-long-001"}', 1),
                *progress_responses,
                SeedanceNzHttpResponse(
                    200,
                    {},
                    b'{"status":"SUCCESS","data":{"result_url":"https://cdn.seedance.nz/long-001.png"}}',
                    1,
                ),
            ],
            download_body=_png(),
        )
        adapter = SeedanceNzImageAdapter(
            api_key="sk-synthetic",
            transport=transport,
            sleep=clock.sleep,
            clock=clock,
        )

        asset = adapter._generate(
            _invocation(timeout_seconds=300.0),
            cancellation=CancellationToken(),
        )

        self.assertEqual(asset.provider_asset_id, "task-long-001")
        self.assertEqual(clock.now, 280.0)
        self.assertEqual([call["method"] for call in transport.calls].count("GET"), 71)
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 1)

    def test_deadline_timeout_preserves_task_id_and_last_status(self) -> None:
        clock = FakeClock()
        transport = RecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-timeout-001"}', 1),
                SeedanceNzHttpResponse(200, {}, b'{"status":"IN_PROGRESS"}', 1),
                SeedanceNzHttpResponse(200, {}, b'{"status":"IN_PROGRESS"}', 1),
                SeedanceNzHttpResponse(200, {}, b'{"status":"IN_PROGRESS"}', 1),
            ]
        )
        adapter = SeedanceNzImageAdapter(
            api_key="sk-synthetic",
            transport=transport,
            sleep=clock.sleep,
            clock=clock,
        )

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(
                _invocation(timeout_seconds=10.0),
                cancellation=CancellationToken(),
            )

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_TIMEOUT)
        self.assertEqual(adapter.last_receipt.task_id, "task-timeout-001")
        self.assertEqual(adapter.last_receipt.poll_count, 3)
        self.assertEqual(adapter.last_receipt.last_status, "IN_PROGRESS")
        self.assertEqual(adapter.last_receipt.terminal_stage, "poll")
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 0)

    def test_poll_failure_preserves_submitted_task_id(self) -> None:
        transport = RecordingTransport([
            SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-failure-identity"}', 1),
            SeedanceNzHttpResponse(
                200,
                {},
                b'{"status":"FAILURE","message":"synthetic failure"}',
                1,
            ),
        ])
        adapter = SeedanceNzImageAdapter(
            api_key="sk-synthetic",
            transport=transport,
            sleep=lambda _: None,
        )

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertEqual(adapter.last_receipt.task_id, "task-failure-identity")
        self.assertEqual(adapter.last_receipt.poll_count, 1)
        self.assertEqual(adapter.last_receipt.last_status, "FAILURE")
        self.assertEqual(adapter.last_receipt.terminal_stage, "poll")
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 0)

    def test_download_failure_preserves_submitted_task_id(self) -> None:
        transport = RecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-download-identity"}', 1),
                SeedanceNzHttpResponse(
                    200,
                    {},
                    b'{"status":"SUCCESS","data":{"result_url":"https://cdn.seedance.nz/signed.png?token=secret"}}',
                    1,
                ),
            ],
            download_error=ImagePanelError(
                ImagePanelErrorCode.PROVIDER_FAILED,
                "Synthetic download failure",
                category="provider",
            ),
        )
        adapter = SeedanceNzImageAdapter(
            api_key="sk-synthetic",
            transport=transport,
            sleep=lambda _: None,
        )

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertEqual(adapter.last_receipt.task_id, "task-download-identity")
        self.assertEqual(adapter.last_receipt.poll_count, 1)
        self.assertEqual(adapter.last_receipt.last_status, "SUCCESS")
        self.assertEqual(adapter.last_receipt.terminal_stage, "download")
        self.assertIsNone(adapter.last_receipt.result_url)
        self.assertNotIn("token=secret", json.dumps(adapter.last_receipt.to_dict()))
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 1)

    def test_happy_path_submits_polls_downloads_and_records_provenance(self) -> None:
        content = _png()
        transport = RecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-001"}', 3),
                SeedanceNzHttpResponse(200, {}, b'{"status":"IN_PROGRESS"}', 2),
                SeedanceNzHttpResponse(
                    200,
                    {},
                    b'{"status":"SUCCESS","data":{"result_url":"https://cdn.seedance.nz/task-001.png"}}',
                    2,
                ),
            ],
            download_body=content,
        )
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)

        asset = adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(asset.content, content)
        self.assertEqual((asset.width, asset.height), (1024, 1024))
        self.assertEqual(asset.provider_asset_id, "task-001")
        self.assertEqual([call["endpoint"] for call in transport.calls], [
            SEEDANCE_NZ_IMAGE_SUBMIT_ENDPOINT,
            SEEDANCE_NZ_IMAGE_TASK_ENDPOINT.format(task_id="task-001"),
            SEEDANCE_NZ_IMAGE_TASK_ENDPOINT.format(task_id="task-001"),
            "https://cdn.seedance.nz/task-001.png",
        ])
        self.assertEqual(transport.calls[0]["payload"], {
            "model": "seedream-v5-pro-t2i",
            "prompt": "Synthetic Seedance product panel",
            "metadata": {"resolution": "1k", "output_format": "jpeg"},
        })
        self.assertEqual(transport.calls[0]["headers"]["Authorization"], "Bearer sk-synthetic")
        self.assertEqual(adapter.last_receipt.task_id, "task-001")
        self.assertEqual(adapter.last_receipt.sha256, __import__("hashlib").sha256(content).hexdigest())

    def test_401_fails_closed_and_redacts_key(self) -> None:
        transport = RecordingTransport([SeedanceNzHttpResponse(401, {}, b"invalid sk-synthetic", 1)])
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED)
        self.assertEqual(adapter.last_receipt.error_body, "invalid [REDACTED]")
        self.assertEqual(len(transport.calls), 1)

    def test_missing_key_is_rejected_before_transport(self) -> None:
        with self.assertRaisesRegex(ValueError, "SEEDANCE_NZ_API_KEY"):
            SeedanceNzImageAdapter(api_key="", transport=RecordingTransport([]))

    def test_poll_failure_is_terminal_and_does_not_download(self) -> None:
        transport = RecordingTransport([
            SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-fail"}', 1),
            SeedanceNzHttpResponse(200, {}, b'{"status":"FAILURE","message":"synthetic failure"}', 1),
        ])
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertEqual(len(transport.calls), 2)

    def test_nested_taskdto_in_progress_then_success_downloads(self) -> None:
        content = _png()
        transport = RecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"data":{"task_id":"task-nested-001"}}', 1),
                SeedanceNzHttpResponse(200, {}, b'{"code":"success","data":{"status":"IN_PROGRESS"}}', 1),
                SeedanceNzHttpResponse(
                    200,
                    {},
                    b'{"code":"success","data":{"status":"SUCCESS","result_url":"https://cdn.seedance.nz/nested-001.png"}}',
                    1,
                ),
            ],
            download_body=content,
        )
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)

        asset = adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(asset.content, content)
        self.assertEqual((asset.width, asset.height), (1024, 1024))
        self.assertEqual(asset.provider_metadata["sha256"], __import__("hashlib").sha256(content).hexdigest())
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 1)

    def test_nested_taskdto_uses_content_image_url_fallback(self) -> None:
        content = _png()
        transport = RecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-nested-002"}', 1),
                SeedanceNzHttpResponse(
                    200,
                    {},
                    b'{"code":"success","data":{"status":"SUCCESS","data":{"status":"succeeded","content":{"image_url":"https://cdn.seedance.nz/nested-002.png"}}}}',
                    1,
                ),
            ],
            download_body=content,
        )
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)

        asset = adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(asset.content, content)
        self.assertEqual(transport.calls[-1]["endpoint"], "https://cdn.seedance.nz/nested-002.png")

    def test_nested_taskdto_failure_fails_closed_without_download(self) -> None:
        transport = RecordingTransport([
            SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-nested-fail"}', 1),
            SeedanceNzHttpResponse(
                200,
                {},
                b'{"code":"success","data":{"status":"FAILURE","fail_reason":"synthetic nested failure"}}',
                1,
            ),
        ])
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertEqual(captured.exception.details["provider_summary"], "synthetic nested failure")
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 0)

    def test_nested_taskdto_unknown_status_fails_closed(self) -> None:
        transport = RecordingTransport([
            SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-nested-unknown"}', 1),
            SeedanceNzHttpResponse(200, {}, b'{"code":"success","data":{"status":"QUEUED_ELSEWHERE"}}', 1),
        ])
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertEqual(adapter.last_receipt.task_id, "task-nested-unknown")
        self.assertEqual(adapter.last_receipt.last_status, "UNKNOWN")
        self.assertEqual(adapter.last_receipt.terminal_stage, "poll")
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 0)

    def test_nested_taskdto_submitted_is_a_processing_status(self) -> None:
        content = _png()
        transport = RecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-submitted"}', 1),
                SeedanceNzHttpResponse(200, {}, b'{"data":{"status":"SUBMITTED"}}', 1),
                SeedanceNzHttpResponse(
                    200,
                    {},
                    b'{"data":{"status":"SUCCESS","result_url":"https://cdn.seedance.nz/submitted.png"}}',
                    1,
                ),
            ],
            download_body=content,
        )
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)

        asset = adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(asset.content, content)
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 1)

    def test_nested_taskdto_non_https_url_fails_before_download(self) -> None:
        transport = RecordingTransport([
            SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-http-url"}', 1),
            SeedanceNzHttpResponse(
                200,
                {},
                b'{"data":{"status":"SUCCESS","result_url":"http://cdn.seedance.nz/insecure.png"}}',
                1,
            ),
        ])
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED)
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 0)

    def test_nested_taskdto_non_string_status_fails_closed(self) -> None:
        transport = RecordingTransport([
            SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-bad-status"}', 1),
            SeedanceNzHttpResponse(200, {}, b'{"data":{"status":17}}', 1),
        ])
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=transport, sleep=lambda _: None)

        with self.assertRaises(ImagePanelError) as captured:
            adapter._generate(_invocation(), cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertEqual([call["method"] for call in transport.calls].count("GET_BYTES"), 0)

    def test_fake_adapter_is_memory_only_and_supports_failure(self) -> None:
        fake = FakeSeedanceNzImageAdapter(terminal_status="SUCCESS", content=_png())
        asset = fake._generate(_invocation(), cancellation=CancellationToken())
        self.assertEqual(asset.provider_asset_id, "seedance-nz-fake-task-001")
        self.assertEqual(fake.network_calls, 0)

        rejecting = FakeSeedanceNzImageAdapter(terminal_status="FAILURE")
        with self.assertRaises(ImagePanelError) as captured:
            rejecting._generate(_invocation(), cancellation=CancellationToken())
        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_FAILED)
        self.assertEqual(rejecting.network_calls, 0)

    def test_i2i_adds_explicit_reference_urls_and_rejects_more_than_ten(self) -> None:
        content = _png()
        transport = RecordingTransport(
            [
                SeedanceNzHttpResponse(200, {}, b'{"task_id":"task-i2i"}', 1),
                SeedanceNzHttpResponse(200, {}, b'{"status":"SUCCESS","data":{"result_url":"https://cdn.seedance.nz/i2i.png"}}', 1),
            ],
            download_body=content,
        )
        adapter = SeedanceNzImageAdapter(
            api_key="sk-synthetic",
            transport=transport,
            sleep=lambda _: None,
            reference_image_urls={"panel-synthetic-004": ("https://assets.example/ref.png",)},
        )
        adapter._generate(_invocation(model_id="seedream-v5-pro-i2i"), cancellation=CancellationToken())
        self.assertEqual(transport.calls[0]["payload"]["images"], ["https://assets.example/ref.png"])

        with self.assertRaisesRegex(ValueError, "at most 10"):
            SeedanceNzImageAdapter(
                api_key="sk-synthetic",
                transport=RecordingTransport([]),
                reference_image_urls={"panel-synthetic-004": tuple("https://e/" + str(i) for i in range(11))},
            )

    def test_direct_public_generate_remains_fail_closed(self) -> None:
        adapter = SeedanceNzImageAdapter(api_key="sk-synthetic", transport=RecordingTransport([]))
        with self.assertRaises(ImagePanelError) as captured:
            adapter.generate(None, cancellation=CancellationToken())
        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_BYPASS_FORBIDDEN)

    def test_download_allowlist_accepts_seedance_cdn_but_rejects_external_host(self) -> None:
        called: list[tuple[tuple[object, ...], dict[str, object]]] = []
        client = SeedanceNzHttpClient(connection_factory=lambda *args, **kwargs: called.append((args, kwargs)))
        with self.assertRaises(ImagePanelError) as captured:
            client.get_bytes("https://example.invalid/panel.png", headers={}, timeout_seconds=1)
        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED)
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
