"""Machine-readable owner CLI for Video Generation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from time import monotonic, sleep as system_sleep
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from .adapters import AdapterFailure
from .cli_ledger import (
    ARTIFACT_NAME,
    RECEIPT_NAME,
    SeedanceNzCliLedger,
    SeedanceNzSubmissionRegistry,
    resolve_output_directory,
    resolve_submission_registry_directory,
)
from .errors import GenerationError, GenerationErrorCode, contains_sensitive_text
from .interface import VideoGenerationInterface
from .models import canonical_json, content_digest, snapshot
from .seedance_nz_adapter import MODEL_ID, SeedanceNzVideoProviderAdapter


AUTHORIZATION_ID = "FTG-0-20260720-001"
POLL_INTERVAL_SECONDS = 4.0
MAX_DEADLINE_SECONDS = 600.0
MAX_PROVIDER_DURATION_MS = 15_000


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


def _validate_long_timeline_segment(
    document: Mapping[str, object],
    inspected: Mapping[str, object],
    *,
    seconds: str,
) -> None:
    package = document.get("execution_package")
    if not isinstance(package, Mapping):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Execution package is required")
    master = package.get("video_generation_storyboard_master")
    if not isinstance(master, Mapping):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Storyboard master is required")
    shots = master.get("shots")
    entries = master.get("master_panel_entries")
    if not isinstance(shots, list) or not isinstance(entries, list):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Storyboard timeline is invalid")
    typed_shots = [shot for shot in shots if isinstance(shot, Mapping)]
    typed_entries = [entry for entry in entries if isinstance(entry, Mapping)]
    if len(typed_shots) != len(shots) or len(typed_entries) != len(entries):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Storyboard timeline is invalid")
    durations = [shot.get("duration_ms") for shot in typed_shots]
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in durations):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Storyboard timeline is invalid")
    total_duration_ms = sum(durations)
    if total_duration_ms <= MAX_PROVIDER_DURATION_MS:
        return

    def invalid(message: str, field: str = "output.metadata.execution_segment") -> None:
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, message, field_paths=(field,))

    output = inspected.get("output")
    metadata = output.get("metadata") if isinstance(output, Mapping) else None
    segment = metadata.get("execution_segment") if isinstance(metadata, Mapping) else None
    content = metadata.get("content") if isinstance(metadata, Mapping) else None
    if not isinstance(segment, Mapping) or not isinstance(content, list):
        invalid("Long timelines require one declared execution segment and its scoped references")
    required = {
        "segment_id", "start_ms", "end_ms", "duration_ms", "shot_ids", "panel_ids", "sheet_sha256s",
    }
    if set(segment) != required:
        invalid("Execution segment fields are incomplete or unknown")
    segment_id = segment.get("segment_id")
    start_ms = segment.get("start_ms")
    end_ms = segment.get("end_ms")
    duration_ms = segment.get("duration_ms")
    shot_ids = segment.get("shot_ids")
    panel_ids = segment.get("panel_ids")
    sheet_sha256s = segment.get("sheet_sha256s")
    if (
        not isinstance(segment_id, str)
        or not segment_id.startswith("SEG-")
        or not segment_id.removeprefix("SEG-").isdigit()
        or any(isinstance(value, bool) or not isinstance(value, int) for value in (start_ms, end_ms, duration_ms))
        or not isinstance(shot_ids, list)
        or not shot_ids
        or any(not isinstance(value, str) or not value for value in shot_ids)
        or not isinstance(panel_ids, list)
        or not panel_ids
        or any(not isinstance(value, str) or not value for value in panel_ids)
        or not isinstance(sheet_sha256s, list)
        or not sheet_sha256s
        or any(
            not isinstance(digest, str)
            or len(digest) != 71
            or not digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in digest.removeprefix("sha256:"))
            for digest in sheet_sha256s
        )
    ):
        invalid("Execution segment identity, timeline, or Sheet digest is invalid")
    assert isinstance(start_ms, int) and isinstance(end_ms, int) and isinstance(duration_ms, int)
    if duration_ms <= 0 or duration_ms > MAX_PROVIDER_DURATION_MS or end_ms - start_ms != duration_ms:
        invalid("Execution segment must be a positive contiguous block of at most 15 seconds")
    if duration_ms != int(seconds) * 1000:
        invalid("Requested Provider duration must equal the execution segment duration", "output.seconds")

    full_shot_order = [str(shot.get("shot_id")) for shot in typed_shots]
    try:
        positions = [full_shot_order.index(shot_id) for shot_id in shot_ids]
    except ValueError:
        invalid("Execution segment contains an unknown Shot")
    if positions != list(range(positions[0], positions[-1] + 1)):
        invalid("Execution segment Shots must be one consecutive block")
    expected_start = sum(int(durations[index]) for index in range(positions[0]))
    expected_duration = sum(int(durations[index]) for index in positions)
    if start_ms != expected_start or duration_ms != expected_duration or end_ms != expected_start + expected_duration:
        invalid("Execution segment timeline must align with whole consecutive Shots")

    panel_to_shot = {str(entry.get("panel_id")): str(entry.get("shot_id")) for entry in typed_entries}
    expected_panels = [
        str(entry.get("panel_id"))
        for entry in typed_entries
        if str(entry.get("shot_id")) in shot_ids
    ]
    if panel_ids != expected_panels:
        invalid("Execution segment Panel order must exactly cover its Shots")

    production_panels: list[str] = []
    structure_sheets: list[Mapping[str, object]] = []
    for index, raw_item in enumerate(content):
        if not isinstance(raw_item, Mapping):
            invalid("Execution references must be objects", f"output.metadata.content[{index}]")
        role = raw_item.get("reference_role")
        if role == "production_panel":
            panel_id = raw_item.get("panel_id")
            shot_id = raw_item.get("shot_id")
            if not isinstance(panel_id, str) or panel_to_shot.get(panel_id) != shot_id:
                invalid("Production Panel reference is not bound to its canonical Shot", f"output.metadata.content[{index}]")
            production_panels.append(panel_id)
        elif role == "storyboard_structure_reference":
            structure_sheets.append(raw_item)
    if production_panels != expected_panels:
        invalid("Provider references must contain only the current segment's ordered Panels", "output.metadata.content")
    if len(structure_sheets) != len(sheet_sha256s):
        invalid("Long timeline execution must include every declared segment Sheet page", "output.metadata.content")
    for sheet, expected_digest in zip(structure_sheets, sheet_sha256s, strict=True):
        if (
            sheet.get("storyboard_scope") != "execution_segment"
            or sheet.get("segment_id") != segment_id
            or sheet.get("sha256") != expected_digest
        ):
            invalid("Full Master Sheet cannot be submitted for a segmented Provider task", "output.metadata.content")


def _submitted_at(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_execution_value(value: object, *, field: str = "") -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_execution_value(nested, field=str(key))
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_stable_execution_value(item) for item in value]
    if field == "url" and isinstance(value, str):
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))
    return value


def _execution_fingerprint(
    inspected: Mapping[str, object],
    document: Mapping[str, object],
) -> str:
    binding = inspected["provider_binding"]
    output = inspected["output"]
    package = document.get("execution_package")
    mappings = package.get("asset_mapping") if isinstance(package, Mapping) else None
    if not isinstance(binding, Mapping) or not isinstance(output, Mapping) or not isinstance(mappings, list):
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Seedance.nz execution identity is invalid")
    assets: list[dict[str, object]] = []
    for mapping in mappings:
        if not isinstance(mapping, Mapping):
            raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Seedance.nz execution asset identity is invalid")
        assets.append({
            key: mapping[key]
            for key in ("role", "sha256", "shot_id", "panel_id", "provider_execution_input")
            if key in mapping
        })
    return content_digest({
        "provider_id": binding.get("provider_id"),
        "model_id": binding.get("model_id"),
        "assets": assets,
        "output": _stable_execution_value(output),
    })


def _confirm_seedance_submission(summary: Mapping[str, object]) -> bool:
    try:
        import ctypes

        message = (
            "This action submits one paid Seedance video generation task.\n\n"
            f"Project: {summary['project']}\n"
            f"Package: {summary['package_id']}\n"
            f"Model: {summary['model']}\n"
            f"Duration: {summary['seconds']} seconds\n"
            f"Resolution: {summary['resolution']}\n\n"
            "Click Yes only if you explicitly approve this video generation now."
        )
        flags = 0x00000004 | 0x00000030 | 0x00000100 | 0x00040000
        return ctypes.windll.user32.MessageBoxW(None, message, "Approve paid video generation", flags) == 6
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def execute_seedance_nz(
    document: Mapping[str, object],
    *,
    input_path: Path,
    output_dir: Path,
    now: datetime | None = None,
    adapter: object | None = None,
    clock: Callable[[], float] = monotonic,
    sleep: Callable[[float], None] = system_sleep,
    confirm_submission: Callable[[Mapping[str, object]], bool] | None = None,
) -> dict[str, object]:
    """Run the explicitly authorized Seedance.nz chain and persist safe evidence."""

    inspected = VideoGenerationInterface().inspect_video_request(document, now=now)
    model, seconds, resolution, deadline_seconds = _seedance_request_fields(inspected)
    _validate_long_timeline_segment(document, inspected, seconds=seconds)
    resolved_output = resolve_output_directory(input_path, output_dir)
    idempotency_key = str(inspected["idempotency_key"])
    request_hash = str(inspected["request_hash"])
    ledger = SeedanceNzCliLedger(resolved_output)
    replay = ledger.replay(idempotency_key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay
    execution_fingerprint = _execution_fingerprint(inspected, document)
    registry = SeedanceNzSubmissionRegistry(
        resolve_submission_registry_directory(input_path),
        execution_fingerprint,
    )
    registry.ensure_available()
    if confirm_submission is None:
        raise GenerationError(
            GenerationErrorCode.APPROVAL_REQUIRED,
            "Live human confirmation is required immediately before paid video submission",
        )
    confirmation_summary = snapshot({
        "project": next(
            (parent.name for parent in input_path.resolve().parents if parent.parent.name == "run"),
            input_path.resolve().parent.name,
        ),
        "package_id": inspected["package_id"],
        "approval_id": inspected["approval_id"],
        "model": model,
        "seconds": seconds,
        "resolution": resolution,
        "execution_fingerprint": execution_fingerprint,
    })
    try:
        confirmed = confirm_submission(confirmation_summary)
    except Exception:
        confirmed = False
    if confirmed is not True:
        raise GenerationError(
            GenerationErrorCode.APPROVAL_REQUIRED,
            "Paid video submission was not confirmed by the user",
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
        registry.reserve(
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            approval_id=str(inspected["approval_id"]),
            output_dir=resolved_output,
            reserved_at=_submitted_at(now),
        )
        provider = adapter or SeedanceNzVideoProviderAdapter(
            resolution=resolution,
            remaining_attempts=1,
            timeout_seconds=deadline_seconds,
            clock=clock,
        )
        try:
            submit_calls += 1
            provider_job_id = provider.submit(inspected)
        except AdapterFailure as error:
            raise _adapter_failure(error) from None
        if not isinstance(provider_job_id, str) or not provider_job_id or contains_sensitive_text(provider_job_id):
            raise GenerationError(GenerationErrorCode.PROVIDER_REJECTED, "Seedance.nz returned an invalid task identity")
        submitted_at = _submitted_at(now)
        ledger.persist_pending({
            "task_id": provider_job_id,
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
            "submitted_at": submitted_at,
        })
        registry.mark_submitted(task_id=provider_job_id, submitted_at=submitted_at)
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
            "submitted_at": submitted_at,
            "artifact_file": ARTIFACT_NAME,
            "receipt_file": RECEIPT_NAME,
            "release_status": "CONTROLLED_FIRST_RUN_REQUIRED",
            "replayed": False,
        })
        receipt["receipt_digest"] = "sha256:" + hashlib.sha256(canonical_json(receipt).encode("utf-8")).hexdigest()
        ledger.promote(content, receipt)
        registry.mark_downloaded(receipt_digest=str(receipt["receipt_digest"]))
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
                confirm_submission=_confirm_seedance_submission,
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
