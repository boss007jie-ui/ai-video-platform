from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from threading import Event, Thread
import unittest

from ai_video_platform.contracts import validate_envelope
from ai_video_platform.skills.product_image_panel_generation import (
    CancellationToken,
    FakeImageProviderAdapter,
    FakeProviderStep,
    GenerationItem,
    GenerationStatus,
    ImagePanelError,
    ImagePanelErrorCode,
    ImagePanelService,
)

from ._support import ASSET_ID, make_request, profile, rebind_request
from ai_video_platform.skills.product_image_panel_generation import GenerationCommand


class ImagePanelAdapterTests(unittest.TestCase):
    def make_service(self, adapter, *, sleep=lambda _seconds: None, max_concurrency: int = 1):
        return ImagePanelService(
            provider=adapter,
            profiles=(profile(),),
            now=lambda: datetime(2026, 7, 20, 10, 1, tzinfo=timezone.utc),
            sleep=sleep,
            max_concurrency=max_concurrency,
        )

    def test_fake_adapter_success_emits_auditable_foundation_outputs(self) -> None:
        content = b"synthetic-panel-bytes"
        adapter = FakeImageProviderAdapter(
            script={"panel-synthetic-004": [FakeProviderStep.success(content=content)]}
        )

        outcome = self.make_service(adapter).generate_panel(make_request())

        self.assertEqual(outcome.status, GenerationStatus.COMPLETED)
        self.assertFalse(outcome.replayed)
        self.assertEqual(outcome.generation_record.total_attempts, 1)
        self.assertEqual(outcome.generation_record.total_cost_units, 3)
        self.assertEqual(outcome.asset_manifest.contract_type, "avp.contract.asset-manifest")
        self.assertEqual(outcome.feedback_event.contract_type, "avp.contract.feedback-event")
        self.assertEqual(outcome.execution_event.contract_type, "avp.contract.skill-execution-event")
        validate_envelope(outcome.asset_manifest)
        validate_envelope(outcome.feedback_event)
        validate_envelope(outcome.execution_event)
        asset = outcome.asset_manifest.payload["assets"][0]
        self.assertEqual(asset["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(asset["derived_from"], (ASSET_ID,))

    def test_product_image_command_is_independently_callable(self) -> None:
        adapter = FakeImageProviderAdapter()
        request = make_request(command=GenerationCommand.GENERATE_PRODUCT_IMAGE)

        outcome = self.make_service(adapter).generate_product_image(request)

        self.assertEqual(outcome.status, GenerationStatus.COMPLETED)
        self.assertEqual(outcome.asset_manifest.payload["assets"][0]["role"], "product-image")

    def test_retryable_failure_retries_with_injected_backoff_then_succeeds(self) -> None:
        sleeps: list[float] = []
        adapter = FakeImageProviderAdapter(
            script={
                "panel-synthetic-004": [
                    FakeProviderStep.failure("transient", retryable=True),
                    FakeProviderStep.success(),
                ]
            }
        )

        outcome = self.make_service(adapter, sleep=sleeps.append).generate_panel(make_request())

        self.assertEqual(outcome.status, GenerationStatus.COMPLETED)
        self.assertEqual(adapter.attempts_for("panel-synthetic-004"), 2)
        self.assertEqual(sleeps, [0.05])
        self.assertEqual(outcome.generation_record.total_cost_units, 6)

    def test_prompt_compilation_is_deterministic_and_product_bound(self) -> None:
        adapter = FakeImageProviderAdapter()
        request = make_request()

        self.make_service(adapter).generate_panel(request)

        compiled = adapter.invocations[0].compiled_prompt
        self.assertEqual(
            compiled,
            "role=panel\n"
            "product_id=product-synthetic-004\n"
            "size=1024x1024\n"
            "approved_asset_ids=asset-approved-004\n"
            "instruction=Synthetic clean-room product panel",
        )
        self.assertNotIn("approval-boundary", compiled)

    def test_non_retryable_failure_is_not_retried(self) -> None:
        adapter = FakeImageProviderAdapter(
            script={"panel-synthetic-004": [FakeProviderStep.failure("invalid", retryable=False)]}
        )

        outcome = self.make_service(adapter).generate_panel(make_request())

        self.assertEqual(outcome.status, GenerationStatus.FAILED)
        self.assertEqual(adapter.attempts_for("panel-synthetic-004"), 1)
        self.assertEqual(outcome.generation_record.items[0].error["code"], ImagePanelErrorCode.PROVIDER_FAILED.value)

    def test_timeout_is_terminal_and_redacted(self) -> None:
        adapter = FakeImageProviderAdapter(
            script={"panel-synthetic-004": [FakeProviderStep.timeout(details={"authorization": "synthetic-sensitive"})]}
        )

        outcome = self.make_service(adapter).generate_panel(make_request())

        self.assertEqual(outcome.status, GenerationStatus.FAILED)
        error = outcome.generation_record.items[0].error
        self.assertEqual(error["code"], ImagePanelErrorCode.PROVIDER_TIMEOUT.value)
        self.assertEqual(error["details"]["authorization"], "[REDACTED]")
        self.assertNotIn("synthetic-sensitive", str(outcome))

    def test_pre_cancelled_request_never_reaches_provider(self) -> None:
        token = CancellationToken()
        token.cancel()
        adapter = FakeImageProviderAdapter()

        outcome = self.make_service(adapter).generate_panel(make_request(), cancellation=token)

        self.assertEqual(outcome.status, GenerationStatus.CANCELLED)
        self.assertEqual(adapter.total_attempts, 0)
        self.assertEqual(outcome.execution_event.payload["event_type"], "cancelled")

    def test_mixed_item_outcomes_are_reported_as_partial_failure(self) -> None:
        request = make_request()
        second = GenerationItem(
            item_id="panel-synthetic-005",
            role="panel",
            prompt="Second synthetic panel",
            width=1024,
            height=1024,
            input_asset_ids=(ASSET_ID,),
        )
        request = rebind_request(request, items=(*request.items, second))
        adapter = FakeImageProviderAdapter(
            script={
                "panel-synthetic-004": [FakeProviderStep.success()],
                "panel-synthetic-005": [FakeProviderStep.failure("blocked", retryable=False)],
            }
        )

        outcome = self.make_service(adapter).generate_panel(request)

        self.assertEqual(outcome.status, GenerationStatus.PARTIAL_FAILURE)
        self.assertEqual(len(outcome.asset_manifest.payload["assets"]), 1)
        self.assertEqual([item.status.value for item in outcome.generation_record.items], ["completed", "failed"])

    def test_exact_idempotent_replay_does_not_repeat_provider_side_effect(self) -> None:
        adapter = FakeImageProviderAdapter()
        service = self.make_service(adapter)
        request = make_request()

        first = service.generate_panel(request)
        second = service.generate_panel(request)

        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(adapter.total_attempts, 1)
        self.assertEqual(first.asset_manifest.contract_id, second.asset_manifest.contract_id)

    def test_idempotency_key_reuse_with_changed_request_fails(self) -> None:
        adapter = FakeImageProviderAdapter()
        service = self.make_service(adapter)
        request = make_request()
        service.generate_panel(request)
        changed_item = replace(request.items[0], prompt="Changed synthetic prompt")
        changed = rebind_request(request, items=(changed_item,))

        with self.assertRaises(ImagePanelError) as captured:
            service.generate_panel(changed)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.IDEMPOTENCY_CONFLICT)
        self.assertEqual(adapter.total_attempts, 1)

    def test_concurrency_limit_rejects_second_distinct_request(self) -> None:
        entered = Event()
        release = Event()

        def block(_invocation) -> None:
            entered.set()
            self.assertTrue(release.wait(2.0))

        adapter = FakeImageProviderAdapter(before_generate=block)
        service = self.make_service(adapter, max_concurrency=1)
        first_request = make_request()
        second_request = rebind_request(
            first_request,
            request_id="image-panel-request-synthetic-005",
            idempotency_key="image-panel-idempotency-synthetic-005",
        )
        first_outcome: list[object] = []
        worker = Thread(target=lambda: first_outcome.append(service.generate_panel(first_request)))
        worker.start()
        self.assertTrue(entered.wait(2.0))

        try:
            with self.assertRaises(ImagePanelError) as captured:
                service.generate_panel(second_request)
            self.assertEqual(captured.exception.code, ImagePanelErrorCode.CONCURRENCY_LIMIT_EXCEEDED)
        finally:
            release.set()
            worker.join(2.0)

        self.assertEqual(len(first_outcome), 1)


if __name__ == "__main__":
    unittest.main()
