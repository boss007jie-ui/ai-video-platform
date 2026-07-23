from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import ast
from pathlib import Path
from threading import Event
from time import perf_counter
import unittest

from ai_video_platform.contracts import FOUNDATION_CONTRACT_IDS
from ai_video_platform.contracts.serialization import thaw_json
from ai_video_platform.skills.product_image_panel_generation import (
    CancellationToken,
    FakeImageProviderAdapter,
    GenerationBudget,
    GenerationCommand,
    GenerationStatus,
    ImagePanelError,
    ImagePanelErrorCode,
    ImagePanelService,
    ImageProviderAdapter,
    RejectingImageProviderAdapter,
    calculate_model_profile_digest,
)
from ai_video_platform.skills.product_image_panel_generation import adapters as adapter_module

from ._support import NOW_TEXT, TASK_ID, _envelope, make_request, profile, rebind_request


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "ai_video_platform"
    / "skills"
    / "product_image_panel_generation"
)


class ImagePanelSafetyTests(unittest.TestCase):
    def make_service(self, adapter=None, *, configured_profile=None, max_concurrency=1):
        return ImagePanelService(
            provider=adapter or FakeImageProviderAdapter(),
            profiles=(configured_profile or profile(),),
            now=lambda: datetime(2026, 7, 20, 10, 1, tzinfo=timezone.utc),
            max_concurrency=max_concurrency,
        )

    def test_direct_adapter_call_outside_service_is_blocked(self) -> None:
        adapter = FakeImageProviderAdapter()

        with self.assertRaises(ImagePanelError) as captured:
            adapter.generate(None, cancellation=CancellationToken())

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PROVIDER_BYPASS_FORBIDDEN)
        self.assertEqual(adapter.total_attempts, 0)

    def test_provider_permit_minter_is_not_exposed_at_module_scope(self) -> None:
        self.assertFalse(hasattr(adapter_module, "_issue_provider_permit"))

    def test_rejecting_adapter_fails_without_network_or_provider_payload(self) -> None:
        rejecting_profile = replace(profile(), provider_id="rejecting")
        service = self.make_service(
            RejectingImageProviderAdapter(),
            configured_profile=rejecting_profile,
        )

        outcome = service.generate_panel(
            rebind_request(
                make_request(),
                model_profile_digest=calculate_model_profile_digest(rejecting_profile),
            )
        )

        self.assertEqual(outcome.status, GenerationStatus.FAILED)
        self.assertEqual(
            outcome.generation_record.items[0].error["code"],
            ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED.value,
        )

    def test_missing_approval_never_reaches_adapter(self) -> None:
        adapter = FakeImageProviderAdapter()
        request = replace(make_request(), approval_record=None)

        with self.assertRaises(ImagePanelError) as captured:
            self.make_service(adapter).generate_panel(request)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.APPROVAL_REQUIRED)
        self.assertEqual(adapter.total_attempts, 0)

    def test_missing_product_context_never_reaches_adapter(self) -> None:
        adapter = FakeImageProviderAdapter()
        request = replace(make_request(), product_context=None)

        with self.assertRaises(ImagePanelError) as captured:
            self.make_service(adapter).generate_panel(request)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.PRODUCT_CONTEXT_REQUIRED)
        self.assertEqual(adapter.total_attempts, 0)

    def test_missing_budget_never_reaches_adapter(self) -> None:
        adapter = FakeImageProviderAdapter()
        request = replace(make_request(), budget=None)

        with self.assertRaises(ImagePanelError) as captured:
            self.make_service(adapter).generate_panel(request)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.BUDGET_REQUIRED)
        self.assertEqual(adapter.total_attempts, 0)

    def test_stale_input_never_reaches_adapter(self) -> None:
        adapter = FakeImageProviderAdapter()

        with self.assertRaises(ImagePanelError) as captured:
            self.make_service(adapter).generate_panel(make_request(context_revision=3))

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.STALE_INPUT)
        self.assertEqual(adapter.total_attempts, 0)

    def test_request_concurrency_budget_cannot_exceed_service_limit(self) -> None:
        adapter = FakeImageProviderAdapter()
        request = make_request()
        budget = replace(request.budget, max_concurrency=2)
        request = rebind_request(request, budget=budget)

        with self.assertRaises(ImagePanelError) as captured:
            self.make_service(adapter, max_concurrency=1).generate_panel(request)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.CONCURRENCY_LIMIT_EXCEEDED)
        self.assertEqual(adapter.total_attempts, 0)

    def test_reference_without_rights_assertion_fails_closed(self) -> None:
        reference_manifest = _envelope(
            "avp.contract.reference-manifest",
            {
                "reference_manifest_id": "reference-manifest-synthetic-004",
                "revision": 1,
                "task_id": TASK_ID,
                "references": [
                    {
                        "reference_id": "reference-synthetic-004",
                        "reference_type": "image",
                        "source_uri": "memory://synthetic/reference.png",
                        "sha256": "1" * 64,
                        "usage": "style-only",
                        "provenance": {"source": "synthetic-test"},
                    }
                ],
                "created_at": NOW_TEXT,
            },
            "reference-analysis",
            "skill",
        )
        request = rebind_request(make_request(), reference_manifest=reference_manifest)

        with self.assertRaises(ImagePanelError) as captured:
            self.make_service().generate_panel(request)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.REFERENCE_RIGHTS_UNCONFIRMED)

    def test_asset_manifest_owner_must_match_product_or_task(self) -> None:
        request = make_request()
        payload = thaw_json(request.input_asset_manifests[0].payload)
        payload["owner_id"] = "other-product"
        manifest = _envelope(
            "avp.contract.asset-manifest",
            payload,
            "product-knowledge",
            "skill",
        )
        request = rebind_request(request, input_asset_manifests=(manifest,))

        with self.assertRaises(ImagePanelError) as captured:
            self.make_service().generate_panel(request)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.ASSET_NOT_APPROVED)

    def test_unrelated_contract_correlation_fails_closed(self) -> None:
        request = make_request()
        unrelated_approval = replace(request.approval_record, correlation_id="other-task")
        request = replace(request, approval_record=unrelated_approval)

        with self.assertRaises(ImagePanelError) as captured:
            self.make_service().generate_panel(request)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.CONTRACT_INVALID)

    def test_mid_attempt_cancellation_is_recorded_without_retry(self) -> None:
        token = CancellationToken()
        adapter = FakeImageProviderAdapter(before_generate=lambda _invocation: token.cancel())

        outcome = self.make_service(adapter).generate_panel(make_request(), cancellation=token)

        self.assertEqual(outcome.status, GenerationStatus.CANCELLED)
        self.assertEqual(adapter.total_attempts, 1)
        self.assertEqual(outcome.generation_record.items[0].attempts, 1)

    def test_unexpected_adapter_exception_is_sanitized_into_failed_outcome(self) -> None:
        synthetic = "sk" + "-" + "testonly" + "Z" * 28

        class ExplodingAdapter(ImageProviderAdapter):
            @property
            def provider_id(self) -> str:
                return "offline-fake"

            def _generate(self, *_args, **_kwargs):
                raise RuntimeError(synthetic)

        outcome = self.make_service(ExplodingAdapter()).generate_panel(make_request())

        self.assertEqual(outcome.status, GenerationStatus.FAILED)
        self.assertEqual(
            outcome.generation_record.items[0].error["code"],
            ImagePanelErrorCode.PROVIDER_FAILED.value,
        )
        self.assertNotIn(synthetic, str(outcome))

    def test_provider_error_message_is_replaced_before_public_output(self) -> None:
        synthetic = "sk" + "-" + "testonly" + "Y" * 28

        class LeakyAdapter(ImageProviderAdapter):
            @property
            def provider_id(self) -> str:
                return "offline-fake"

            def _generate(self, *_args, **_kwargs):
                raise ImagePanelError(
                    ImagePanelErrorCode.PROVIDER_FAILED,
                    f"upstream said {synthetic}",
                    category="provider",
                )

        outcome = self.make_service(LeakyAdapter()).generate_panel(make_request())

        self.assertEqual(outcome.status, GenerationStatus.FAILED)
        self.assertEqual(outcome.generation_record.items[0].error["message"], "Provider attempt failed")
        self.assertNotIn(synthetic, str(outcome))

    def test_blocking_adapter_is_cut_off_by_real_timeout_deadline(self) -> None:
        release = Event()

        class BlockingAdapter(ImageProviderAdapter):
            @property
            def provider_id(self) -> str:
                return "offline-fake"

            def _generate(self, *_args, **_kwargs):
                release.wait(2.0)
                raise AssertionError("late adapter result must be ignored")

        request = make_request()
        budget = replace(request.budget, timeout_seconds=0.05)
        request = rebind_request(request, budget=budget)
        started = perf_counter()
        try:
            outcome = self.make_service(BlockingAdapter()).generate_panel(request)
        finally:
            release.set()
        elapsed = perf_counter() - started

        self.assertLess(elapsed, 0.5)
        self.assertEqual(outcome.status, GenerationStatus.FAILED)
        self.assertEqual(
            outcome.generation_record.items[0].error["code"],
            ImagePanelErrorCode.PROVIDER_TIMEOUT.value,
        )

    def test_wrong_public_command_is_rejected_before_adapter(self) -> None:
        adapter = FakeImageProviderAdapter()
        request = make_request(command=GenerationCommand.GENERATE_PRODUCT_IMAGE)

        with self.assertRaises(ImagePanelError) as captured:
            self.make_service(adapter).generate_panel(request)

        self.assertEqual(captured.exception.code, ImagePanelErrorCode.SKILL_BINDING_INVALID)
        self.assertEqual(adapter.total_attempts, 0)

    def test_skill_source_has_no_provider_sdk_or_cross_skill_private_import(self) -> None:
        forbidden_roots = {
            "openai",
            "google.generativeai",
            "replicate",
            "fal_client",
            "ai_video_platform.skills.product_knowledge",
            "ai_video_platform.skills.storyboard",
            "ai_video_platform.skills.video_generation",
        }
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertTrue(
                            all(not alias.name.startswith(root) for root in forbidden_roots),
                            (path, alias.name),
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertTrue(
                        all(not node.module.startswith(root) for root in forbidden_roots),
                        (path, node.module),
                    )

    def test_foundation_registry_remains_exactly_eleven_payload_ids(self) -> None:
        self.assertEqual(len(FOUNDATION_CONTRACT_IDS), 11)
        self.assertEqual(len(set(FOUNDATION_CONTRACT_IDS)), 11)


if __name__ == "__main__":
    unittest.main()
