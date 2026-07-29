from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_generation.adapters import AdapterFailure
from ai_video_platform.skills.video_generation.cli import execute_seedance_nz as raw_execute_seedance_nz, main, run_cli
from ai_video_platform.skills.video_generation.errors import GenerationError, GenerationErrorCode
from ai_video_platform.skills.video_generation.seedance_nz_adapter import (
    SeedanceNzCredentialResolver,
    SeedanceNzVideoProviderAdapter,
)
from tests.skills.video_generation.test_video_generation_interface import generation_request


NOW = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
execute_seedance_nz = partial(raw_execute_seedance_nz, confirm_submission=lambda summary: True)


class ScriptedAdapter:
    network_performed = False

    def __init__(self) -> None:
        self.states = [
            {"state": "running", "status": "submitted", "progress": 0},
            {"state": "running", "status": "in_progress", "progress": 50},
            {"state": "succeeded", "status": "success", "progress": 100},
        ]
        self.content = b"offline-seedance-mp4"
        self.submit_calls = 0
        self.poll_calls = 0
        self.download_calls = 0
        self.network_calls = 0

    def submit(self, request: dict[str, object]) -> str:
        self.submit_calls += 1
        self.network_calls += 1
        return "task-offline-12345678"

    def poll(self, provider_job_id: str) -> dict[str, object]:
        self.poll_calls += 1
        self.network_calls += 1
        return self.states.pop(0)

    def download(self, provider_job_id: str) -> dict[str, object]:
        self.download_calls += 1
        self.network_calls += 1
        return {
            "content": self.content,
            "sha256": "sha256:" + hashlib.sha256(self.content).hexdigest(),
            "uri": "memory://seedance-nz/task-offline-12345678.mp4",
            "content_type": "video/mp4",
        }


class FailingAdapter(ScriptedAdapter):
    def __init__(self, failure_stage: str) -> None:
        super().__init__()
        self.failure_stage = failure_stage

    def submit(self, request: dict[str, object]) -> str:
        if self.failure_stage == "submit":
            self.submit_calls += 1
            raise AdapterFailure("CREDENTIAL_UNAVAILABLE", "credential unavailable", retryable=False)
        return super().submit(request)

    def poll(self, provider_job_id: str) -> dict[str, object]:
        if self.failure_stage == "poll":
            self.poll_calls += 1
            return {"state": "failed", "status": "failure", "progress": 100}
        return super().poll(provider_job_id)

    def download(self, provider_job_id: str) -> dict[str, object]:
        if self.failure_stage == "download":
            self.download_calls += 1
            raise AdapterFailure("DOWNLOAD_FAILED", "download failed", retryable=False)
        return super().download(provider_job_id)


class PendingReceiptObservingAdapter(ScriptedAdapter):
    def __init__(self, receipt_path: Path) -> None:
        super().__init__()
        self.receipt_path = receipt_path
        self.pending_receipt: dict[str, object] | None = None

    def poll(self, provider_job_id: str) -> dict[str, object]:
        if self.pending_receipt is None:
            self.pending_receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        return super().poll(provider_job_id)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class NoNetworkTransport:
    def __init__(self) -> None:
        self.calls = 0

    def request_json(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        raise AssertionError("transport must not be called")

    def download(self, uri: str) -> bytes:
        self.calls += 1
        raise AssertionError("transport must not be called")


def seedance_request() -> dict[str, object]:
    request = generation_request()
    request["budget"]["timeout_seconds"] = 600
    request["provider_binding"] = {
        "binding_ref": "seedance-nz-controlled-first-run",
        "provider_id": "seedance-nz",
        "model_id": "seedance-2.0-fast-multi",
        "credential_ref": "env://SEEDANCE_NZ_API_KEY",
    }
    request["output"] = {
        "prompt": "A clean product showcase with a slow camera orbit.",
        "seconds": "5",
        "resolution": "480p",
        "metadata": {
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "https://assets.example/approved-first-frame.jpg"},
                }
            ]
        },
    }
    return request


class VideoGenerationSeedanceCliTests(unittest.TestCase):
    def test_embedded_approval_cannot_submit_without_live_human_confirmation(self) -> None:
        adapter = ScriptedAdapter()
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            request = seedance_request()
            request_path.write_text(json.dumps(request), encoding="utf-8")

            with self.assertRaises(GenerationError) as captured:
                raw_execute_seedance_nz(
                    request,
                    input_path=request_path,
                    output_dir=workspace / "output",
                    now=NOW,
                    adapter=adapter,
                    clock=clock,
                    sleep=clock.sleep,
                )

            self.assertEqual(captured.exception.code, GenerationErrorCode.APPROVAL_REQUIRED)
            self.assertEqual(adapter.submit_calls, 0)

    def test_same_execution_cannot_resubmit_with_new_approval_key_or_output_dir(self) -> None:
        first_adapter = ScriptedAdapter()
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            first = seedance_request()
            request_path.write_text(json.dumps(first), encoding="utf-8")
            execute_seedance_nz(
                first,
                input_path=request_path,
                output_dir=workspace / "output-a",
                now=NOW,
                adapter=first_adapter,
                clock=clock,
                sleep=clock.sleep,
            )

            duplicate = seedance_request()
            duplicate["idempotency_key"] = "another-idempotency-key"
            duplicate["approval_record"]["approval_id"] = "another-approval-id"
            duplicate["approval_record"]["decision_ref"] = "another-claimed-user-decision"
            duplicate["output"]["metadata"]["content"][0]["image_url"]["url"] += "?q-signature=refreshed"
            duplicate_adapter = ScriptedAdapter()

            with self.assertRaises(GenerationError) as captured:
                execute_seedance_nz(
                    duplicate,
                    input_path=request_path,
                    output_dir=workspace / "output-b",
                    now=NOW,
                    adapter=duplicate_adapter,
                    clock=FakeClock(),
                    sleep=lambda seconds: None,
                )

            self.assertEqual(captured.exception.code, GenerationErrorCode.IDEMPOTENCY_MISMATCH)
            self.assertEqual(duplicate_adapter.submit_calls, 0)

    def test_cli_declined_live_confirmation_does_not_construct_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            request_path.write_text(json.dumps(seedance_request()), encoding="utf-8")
            with (
                patch("ai_video_platform.skills.video_generation.cli.SeedanceNzVideoProviderAdapter") as adapter_class,
                patch("ai_video_platform.skills.video_generation.cli._confirm_seedance_submission", return_value=False),
            ):
                exit_code = main([
                    "execute-seedance-nz",
                    str(request_path),
                    "--output-dir",
                    str(workspace / "output"),
                ])

            self.assertEqual(exit_code, 2)
            adapter_class.assert_not_called()

    def test_submit_persists_pending_receipt_before_first_poll(self) -> None:
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            request = seedance_request()
            request_path.write_text(json.dumps(request), encoding="utf-8")
            output_dir = workspace / "output"
            receipt_path = output_dir / "seedance_nz_video_receipt.json"
            adapter = PendingReceiptObservingAdapter(receipt_path)

            execute_seedance_nz(
                request,
                input_path=request_path,
                output_dir=output_dir,
                now=NOW,
                adapter=adapter,
                clock=clock,
                sleep=clock.sleep,
            )

            pending = adapter.pending_receipt
            self.assertIsNotNone(pending)
            assert pending is not None
            self.assertEqual(set(pending), {"task_id", "idempotency_key", "request_hash", "submitted_at"})
            self.assertEqual(pending["idempotency_key"], request["idempotency_key"])
            self.assertEqual(pending["submitted_at"], "2026-07-20T12:00:00Z")
            self.assertEqual(pending["task_id"], "task-offline-12345678")
            final_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(final_receipt["state"], "downloaded")
            self.assertEqual(final_receipt["submitted_at"], pending["submitted_at"])

    def test_complete_chain_writes_validated_mp4_and_sanitized_receipt(self) -> None:
        adapter = ScriptedAdapter()
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            cli_request = seedance_request()
            cli_request["approval_record"]["valid_until"] = "2099-07-21T08:00:00Z"
            request_path.write_text(json.dumps(cli_request), encoding="utf-8")
            output_dir = workspace / "output"

            result = execute_seedance_nz(
                seedance_request(),
                input_path=request_path,
                output_dir=output_dir,
                now=NOW,
                adapter=adapter,
                clock=clock,
                sleep=clock.sleep,
            )

            self.assertEqual(result["state"], "downloaded")
            self.assertEqual(adapter.submit_calls, 1)
            self.assertEqual(adapter.poll_calls, 3)
            self.assertEqual(adapter.download_calls, 1)
            self.assertEqual(clock.sleeps, [4.0, 4.0])
            self.assertEqual((output_dir / "seedance_nz_video.mp4").read_bytes(), adapter.content)
            receipt = json.loads((output_dir / "seedance_nz_video_receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["release_status"], "CONTROLLED_FIRST_RUN_REQUIRED")
            self.assertEqual(receipt["provider_job_id"], "task-offline-12345678")
            self.assertEqual(receipt["byte_size"], len(adapter.content))
            self.assertEqual(receipt["network_calls"]["submit"], 1)
            self.assertEqual(receipt["network_calls"]["poll"], 3)
            self.assertEqual(receipt["network_calls"]["download"], 1)

    def test_exact_replay_uses_persisted_receipt_with_zero_additional_provider_calls(self) -> None:
        first_adapter = ScriptedAdapter()
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            request = seedance_request()
            request_path.write_text(json.dumps(request), encoding="utf-8")
            output_dir = workspace / "output"
            execute_seedance_nz(
                request,
                input_path=request_path,
                output_dir=output_dir,
                now=NOW,
                adapter=first_adapter,
                clock=clock,
                sleep=clock.sleep,
            )
            replay_adapter = ScriptedAdapter()

            replay = execute_seedance_nz(
                request,
                input_path=request_path,
                output_dir=output_dir,
                now=NOW,
                adapter=replay_adapter,
            )

            self.assertTrue(replay["replayed"])
            self.assertEqual(replay_adapter.submit_calls, 0)
            self.assertEqual(replay_adapter.poll_calls, 0)
            self.assertEqual(replay_adapter.download_calls, 0)

    def test_changed_request_with_same_idempotency_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            request = seedance_request()
            request_path.write_text(json.dumps(request), encoding="utf-8")
            output_dir = workspace / "output"
            clock = FakeClock()
            execute_seedance_nz(
                request,
                input_path=request_path,
                output_dir=output_dir,
                now=NOW,
                adapter=ScriptedAdapter(),
                clock=clock,
                sleep=clock.sleep,
            )
            changed = seedance_request()
            changed["output"]["prompt"] = "A materially changed prompt."

            with self.assertRaises(GenerationError) as captured:
                execute_seedance_nz(
                    changed,
                    input_path=request_path,
                    output_dir=output_dir,
                    now=NOW,
                    adapter=ScriptedAdapter(),
                )

            self.assertEqual(captured.exception.code, GenerationErrorCode.IDEMPOTENCY_MISMATCH)

    def test_tampered_receipt_and_existing_partial_evidence_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            request = seedance_request()
            request_path.write_text(json.dumps(request), encoding="utf-8")
            output_dir = workspace / "output"
            clock = FakeClock()
            execute_seedance_nz(
                request,
                input_path=request_path,
                output_dir=output_dir,
                now=NOW,
                adapter=ScriptedAdapter(),
                clock=clock,
                sleep=clock.sleep,
            )
            receipt_path = output_dir / "seedance_nz_video_receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["status_history"] = []
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            artifact_before = (output_dir / "seedance_nz_video.mp4").read_bytes()

            with self.assertRaises(GenerationError) as captured:
                execute_seedance_nz(
                    request,
                    input_path=request_path,
                    output_dir=output_dir,
                    now=NOW,
                    adapter=ScriptedAdapter(),
                )

            self.assertEqual(captured.exception.code, GenerationErrorCode.IDEMPOTENCY_MISMATCH)
            self.assertEqual((output_dir / "seedance_nz_video.mp4").read_bytes(), artifact_before)

    def test_output_directory_must_be_a_child_of_request_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            request_path = workspace / "request.json"
            request_path.write_text(json.dumps(seedance_request()), encoding="utf-8")

            for output_dir in (workspace, workspace.parent / "escaped"):
                with self.subTest(output_dir=output_dir):
                    with self.assertRaises(GenerationError) as captured:
                        execute_seedance_nz(
                            seedance_request(),
                            input_path=request_path,
                            output_dir=output_dir,
                            now=NOW,
                            adapter=ScriptedAdapter(),
                        )
                    self.assertEqual(captured.exception.code, GenerationErrorCode.INVALID_INPUT)

    def test_provider_failures_retain_task_identity_without_success_artifact(self) -> None:
        cases: list[tuple[str, ScriptedAdapter]] = [
            ("missing-credential", FailingAdapter("submit")),
            ("failed-poll", FailingAdapter("poll")),
            ("download-failure", FailingAdapter("download")),
        ]
        empty = ScriptedAdapter()
        empty.content = b""
        cases.append(("empty", empty))
        wrong_type = ScriptedAdapter()
        original_wrong_download = wrong_type.download
        wrong_type.download = lambda job_id: {**original_wrong_download(job_id), "content_type": "image/jpeg"}
        cases.append(("wrong-type", wrong_type))
        mismatch = ScriptedAdapter()
        original_mismatch_download = mismatch.download
        mismatch.download = lambda job_id: {**original_mismatch_download(job_id), "sha256": "sha256:" + "0" * 64}
        cases.append(("digest-mismatch", mismatch))

        for name, adapter in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                workspace = Path(temp_dir)
                request_path = workspace / "request.json"
                request_path.write_text(json.dumps(seedance_request()), encoding="utf-8")
                output_dir = workspace / "output"
                clock = FakeClock()
                with self.assertRaises(GenerationError):
                    execute_seedance_nz(
                        seedance_request(),
                        input_path=request_path,
                        output_dir=output_dir,
                        now=NOW,
                        adapter=adapter,
                        clock=clock,
                        sleep=clock.sleep,
                    )
                self.assertFalse((output_dir / "seedance_nz_video.mp4").exists())
                receipt_path = output_dir / "seedance_nz_video_receipt.json"
                registry_files = list((workspace / ".seedance_nz_submissions").glob("*.json"))
                self.assertEqual(len(registry_files), 1)
                registry_record = json.loads(registry_files[0].read_text(encoding="utf-8"))
                if name == "missing-credential":
                    self.assertFalse(receipt_path.exists())
                    self.assertEqual(registry_record["state"], "reserved")
                    self.assertNotIn("task_id", registry_record)
                else:
                    pending = json.loads(receipt_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        set(pending),
                        {"task_id", "idempotency_key", "request_hash", "submitted_at"},
                    )
                    self.assertEqual(pending["task_id"], "task-offline-12345678")
                    self.assertEqual(registry_record["task_id"], "task-offline-12345678")

    def test_missing_environment_key_fails_before_transport(self) -> None:
        transport = NoNetworkTransport()
        adapter = SeedanceNzVideoProviderAdapter(
            transport=transport,
            credential_resolver=SeedanceNzCredentialResolver(environ={}),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            request_path.write_text(json.dumps(seedance_request()), encoding="utf-8")
            output_dir = workspace / "output"

            with self.assertRaises(GenerationError) as captured:
                execute_seedance_nz(
                    seedance_request(),
                    input_path=request_path,
                    output_dir=output_dir,
                    now=NOW,
                    adapter=adapter,
                )

            self.assertEqual(captured.exception.code, GenerationErrorCode.PROVIDER_REJECTED)
            self.assertEqual(transport.calls, 0)
            self.assertEqual(adapter.network_calls, 0)

    def test_deadline_stops_without_download_or_late_media_chase(self) -> None:
        adapter = ScriptedAdapter()
        adapter.states = [{"state": "running", "status": "in_progress", "progress": 50}] * 200
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            request_path.write_text(json.dumps(seedance_request()), encoding="utf-8")
            output_dir = workspace / "output"

            with self.assertRaises(GenerationError) as captured:
                execute_seedance_nz(
                    seedance_request(),
                    input_path=request_path,
                    output_dir=output_dir,
                    now=NOW,
                    adapter=adapter,
                    clock=clock,
                    sleep=clock.sleep,
                )

            self.assertEqual(captured.exception.code, GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED)
            self.assertEqual(clock.value, 600.0)
            self.assertTrue(all(interval == 4.0 for interval in clock.sleeps))
            self.assertEqual(adapter.download_calls, 0)
            self.assertFalse((output_dir / "seedance_nz_video.mp4").exists())

    def test_only_explicit_command_constructs_seedance_adapter_and_parser_accepts_output_dir(self) -> None:
        with patch("ai_video_platform.skills.video_generation.cli.SeedanceNzVideoProviderAdapter") as adapter_class:
            result = run_cli("run", seedance_request(), now=NOW)
        self.assertTrue(result["ok"])
        adapter_class.assert_not_called()

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            cli_request = seedance_request()
            cli_request["approval_record"]["valid_until"] = "2099-07-21T08:00:00Z"
            request_path.write_text(json.dumps(cli_request), encoding="utf-8")
            output_dir = workspace / "output"
            fake = ScriptedAdapter()
            fake.states = [{"state": "succeeded", "status": "success", "progress": 100}]
            with (
                patch("ai_video_platform.skills.video_generation.cli.SeedanceNzVideoProviderAdapter", return_value=fake) as adapter_class,
                patch("ai_video_platform.skills.video_generation.cli._confirm_seedance_submission", return_value=True),
            ):
                exit_code = main(["execute-seedance-nz", str(request_path), "--output-dir", str(output_dir)])
            self.assertEqual(exit_code, 0)
            adapter_class.assert_called_once()

    def test_receipt_and_public_result_do_not_expose_key_or_signed_url(self) -> None:
        adapter = ScriptedAdapter()
        signed_url = "https://download.example/video.mp4?signature=do-not-emit"
        adapter.states[-1]["provider_url"] = signed_url
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            request_path = workspace / "request.json"
            request_path.write_text(json.dumps(seedance_request()), encoding="utf-8")
            output_dir = workspace / "output"
            clock = FakeClock()
            result = execute_seedance_nz(
                seedance_request(),
                input_path=request_path,
                output_dir=output_dir,
                now=NOW,
                adapter=adapter,
                clock=clock,
                sleep=clock.sleep,
            )
            rendered = json.dumps(result) + (output_dir / "seedance_nz_video_receipt.json").read_text(encoding="utf-8")
            self.assertNotIn("SEEDANCE_NZ_API_KEY", rendered)
            self.assertNotIn("signature=", rendered)
            self.assertNotIn(signed_url, rendered)


if __name__ == "__main__":
    unittest.main()
