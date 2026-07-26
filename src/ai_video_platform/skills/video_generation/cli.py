"""Machine-readable owner CLI for Video Generation."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from time import monotonic, sleep as system_sleep
from typing import Callable, Mapping, Sequence

from .adapters import AdapterFailure
from .cli_ledger import ARTIFACT_NAME, RECEIPT_NAME, SeedanceNzCliLedger, resolve_output_directory
from .errors import GenerationError, GenerationErrorCode, contains_sensitive_text
from .interface import VideoGenerationInterface
from .models import canonical_json, content_digest, snapshot
from .seedance_nz_adapter import MODEL_ID, SeedanceNzVideoProviderAdapter


AUTHORIZATION_ID = "FTG-0-20260720-001"
POLL_INTERVAL_SECONDS = 4.0
MAX_DEADLINE_SECONDS = 600.0


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Invalid CLI arguments", field_paths=("arguments",))


def run_cli(
    command: str,
    document: Mapping[str, object],
    *,
    now: datetime | None = None,
    interface: VideoGenerationInterface | None = None,
) -> dict[str, object]:
    service = interface or VideoGenerationInterface()
    try:
        if command in {"inspect-video-request", "run"}:
            result = service.inspect_video_request(document, now=now)
        elif command == "submit-video":
            result = service.submit_video(document, now=now)
        elif command in {"poll-video", "cancel-video", "download-video", "recover-video"}:
            job_id = document.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise GenerationError(GenerationErrorCode.INVALID_INPUT, "job_id is required", field_paths=("job_id",))
            operation = {
                "poll-video": service.poll_video,
                "cancel-video": service.cancel_video,
                "download-video": service.download_video,
                "recover-video": service.recover_video,
            }[command]
            result = operation(job_id, now=now)
        else:
            raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Unsupported command")
        return {"ok": True, "exit_code": 0, "result": result}
    except GenerationError as error:
        return {"ok": False, "exit_code": 2, "error": error.to_dict()}


def _adapter_failure(error: AdapterFailure) -> GenerationError:
    details: dict[str, object] = {}
    if error.http_status is not None:
        details["http_status"] = error.http_status
    if error.provider_error_summary is not None:
        details["provider_error_summary"] = error.provider_error_summary
    return GenerationError(
        GenerationErrorCode.PROVIDER_REJECTED,
        str(error),
        details=details,
        retryable=False,
    )


def _seedance_request_fields(inspected: Mapping[str, object]) -> tuple[str, str, str, float]:
    binding = inspected.get("provider_binding")
    output = inspected.get("output")
    budget = inspected.get("budget")
    if (
        not isinstance(binding, Mapping)
        or binding.get("provider_id") != "seedance-nz"
        or binding.get("model_id") != MODEL_ID
        or not isinstance(output, Mapping)
        or not isinstance(budget, Mapping)
    ):
        raise GenerationError(GenerationErrorCode.PROVIDER_BINDING_INVALID, "Seedance.nz binding is required")
    prompt = output.get("prompt")
    seconds = output.get("seconds", output.get("duration_seconds"))
    resolution = output.get("resolution")
    timeout = budget.get("timeout_seconds")
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or isinstance(seconds, bool)
        or not isinstance(seconds, (int, str))
        or not str(seconds).isdigit()
        or not 1 <= int(str(seconds)) <= 15
        or resolution != "480p"
        or isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 1 <= timeout <= int(MAX_DEADLINE_SECONDS)
    ):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Seedance.nz execution settings are invalid")
    return MODEL_ID, str(seconds), resolution, float(timeout)


def execute_seedance_nz(
    document: Mapping[str, object],
    *,
    input_path: Path,
    output_dir: Path,
    now: datetime | None = None,
    adapter: object | None = None,
    clock: Callable[[], float] = monotonic,
    sleep: Callable[[float], None] = system_sleep,
) -> dict[str, object]:
    """Run the explicitly authorized Seedance.nz chain and persist safe evidence."""

    inspected = VideoGenerationInterface().inspect_video_request(document, now=now)
    model, seconds, resolution, deadline_seconds = _seedance_request_fields(inspected)
    resolved_output = resolve_output_directory(input_path, output_dir)
    idempotency_key = str(inspected["idempotency_key"])
    request_hash = str(inspected["request_hash"])
    ledger = SeedanceNzCliLedger(resolved_output)
    replay = ledger.replay(idempotency_key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay

    provider = adapter or SeedanceNzVideoProviderAdapter(
        resolution=resolution,
        remaining_attempts=1,
        timeout_seconds=deadline_seconds,
        clock=clock,
    )
    job_id = "job-" + content_digest({
        "request_hash": request_hash,
        "idempotency_key": idempotency_key,
    }).removeprefix("sha256:")[:20]
    status_history: list[dict[str, object]] = []
    submit_calls = 0
    poll_calls = 0
    download_calls = 0
    ledger.acquire()
    try:
        try:
            submit_calls += 1
            provider_job_id = provider.submit(inspected)
        except AdapterFailure as error:
            raise _adapter_failure(error) from None
        if not isinstance(provider_job_id, str) or not provider_job_id or contains_sensitive_text(provider_job_id):
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Seedance.nz returned an invalid task identity")
        status_history.append({"state": "submitted"})
        started_at = clock()
        while True:
            if clock() - started_at >= deadline_seconds:
                raise GenerationError(GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED, "Seedance.nz execution reached its approved deadline")
            try:
                poll_calls += 1
                raw_state = provider.poll(provider_job_id)
            except AdapterFailure as error:
                raise _adapter_failure(error) from None
            if not isinstance(raw_state, Mapping):
                raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Seedance.nz returned malformed poll data")
            state = raw_state.get("state")
            status = raw_state.get("status")
            progress = raw_state.get("progress")
            allowed_statuses = {"queued", "not_start", "submitted", "in_progress", "completed", "success", "failed", "failure"}
            if (
                state not in {"running", "succeeded", "failed"}
                or not isinstance(status, str)
                or status not in allowed_statuses
                or contains_sensitive_text(status)
                or isinstance(progress, bool)
                or not isinstance(progress, int)
                or not 0 <= progress <= 100
            ):
                raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Seedance.nz returned malformed public poll data")
            observation: dict[str, object] = {"state": state}
            if isinstance(status, str):
                observation["status"] = status
            if isinstance(progress, int) and not isinstance(progress, bool):
                observation["progress"] = progress
            status_history.append(observation)
            if state == "succeeded":
                break
            if state == "failed":
                raise GenerationError(
                    GenerationErrorCode.PROVIDER_REJECTED,
                    "Seedance.nz video generation failed",
                    details={"provider_error_summary": raw_state.get("provider_error_summary")},
                )
            if state != "running":
                raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Seedance.nz returned an unsupported public state")
            remaining = deadline_seconds - (clock() - started_at)
            if remaining <= POLL_INTERVAL_SECONDS:
                if remaining > 0:
                    sleep(remaining)
                raise GenerationError(GenerationErrorCode.PROVIDER_RETRY_EXHAUSTED, "Seedance.nz execution reached its approved deadline")
            sleep(POLL_INTERVAL_SECONDS)

        try:
            download_calls += 1
            artifact = provider.download(provider_job_id)
        except AdapterFailure as error:
            raise _adapter_failure(error) from None
        if not isinstance(artifact, Mapping):
            raise GenerationError(GenerationErrorCode.DOWNLOAD_INTEGRITY_FAILED, "Downloaded Seedance.nz artifact metadata is invalid")
        content = artifact.get("content")
        expected_digest = artifact.get("sha256")
        content_type = artifact.get("content_type")
        if not isinstance(content, bytes) or not content or content_type != "video/mp4" or not isinstance(expected_digest, str):
            raise GenerationError(GenerationErrorCode.DOWNLOAD_INTEGRITY_FAILED, "Downloaded Seedance.nz artifact metadata is invalid")
        actual_digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual_digest != expected_digest:
            raise GenerationError(GenerationErrorCode.DOWNLOAD_INTEGRITY_FAILED, "Downloaded Seedance.nz artifact digest mismatch")
        network_total = getattr(provider, "network_calls", submit_calls + poll_calls + download_calls)
        if isinstance(network_total, bool) or not isinstance(network_total, int) or network_total < 0:
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Seedance.nz network call observation is invalid")
        receipt = snapshot({
            "authorization_id": AUTHORIZATION_ID,
            "job_id": job_id,
            "provider_job_id": provider_job_id,
            "state": "downloaded",
            "status_history": status_history,
            "model": model,
            "requested_seconds": seconds,
            "requested_resolution": resolution,
            "byte_size": len(content),
            "sha256": actual_digest,
            "content_type": "video/mp4",
            "network_calls": {
                "submit": submit_calls,
                "poll": poll_calls,
                "download": download_calls,
                "total": network_total,
            },
            "request_hash": request_hash,
            "idempotency_key": idempotency_key,
            "artifact_file": ARTIFACT_NAME,
            "receipt_file": RECEIPT_NAME,
            "release_status": "CONTROLLED_FIRST_RUN_REQUIRED",
            "replayed": False,
        })
        receipt["receipt_digest"] = "sha256:" + hashlib.sha256(canonical_json(receipt).encode("utf-8")).hexdigest()
        ledger.persist(content, receipt)
        return receipt
    finally:
        ledger.release()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _JsonArgumentParser(prog="video-generation")
    parser.add_argument("command", choices=(
        "inspect-video-request", "run", "submit-video", "poll-video", "cancel-video",
        "download-video", "recover-video", "execute-seedance-nz",
    ))
    parser.add_argument("input", help="UTF-8 JSON request file or '-' for stdin")
    parser.add_argument("--output-dir")
    try:
        args = parser.parse_args(argv)
        if args.command == "execute-seedance-nz":
            if args.input == "-" or not isinstance(args.output_dir, str) or not args.output_dir:
                raise GenerationError(
                    GenerationErrorCode.INVALID_INPUT,
                    "execute-seedance-nz requires an input file and --output-dir",
                    field_paths=("input", "output_dir"),
                )
        elif args.output_dir is not None:
            raise GenerationError(GenerationErrorCode.INVALID_INPUT, "--output-dir is only valid for execute-seedance-nz")
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError
        if args.command == "execute-seedance-nz":
            execution = execute_seedance_nz(
                document,
                input_path=Path(args.input),
                output_dir=Path(args.output_dir),
            )
            result = {"ok": True, "exit_code": 0, "result": execution}
        else:
            result = run_cli(args.command, document)
    except GenerationError as error:
        result = {"ok": False, "exit_code": 2, "error": error.to_dict()}
    except (OSError, ValueError, json.JSONDecodeError):
        result = {"ok": False, "exit_code": 2, "error": GenerationError(GenerationErrorCode.INVALID_INPUT, "Input must be a readable UTF-8 JSON object").to_dict()}
    print(canonical_json(result))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
