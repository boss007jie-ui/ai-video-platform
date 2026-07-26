"""Machine-readable offline CLI for Video Enhancement."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence

from .adapters import AdapterFailure, RejectingVideoEnhancementAdapter
from .errors import EnhancementError, EnhancementErrorCode
from .interface import VideoEnhancementInterface
from .models import canonical_json, content_digest, snapshot
from .runninghub_adapter import FakeRunningHubVideoEnhancementAdapter, RunningHubVideoEnhancementAdapter
from .runninghub_ledger import ARTIFACT_NAME, RECEIPT_NAME, RunningHubCliLedger


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "Invalid CLI arguments", field_paths=("arguments",))


def run_cli(
    command: str,
    document: Mapping[str, object],
    *,
    now: datetime | None = None,
    interface: VideoEnhancementInterface | None = None,
) -> dict[str, object]:
    service = interface or VideoEnhancementInterface()
    try:
        if command == "inspect-enhancement-request":
            result = service.inspect_enhancement_request(document, now=now)
        elif command == "submit-enhancement":
            result = service.submit_enhancement(document, now=now)
        elif command in {
            "poll-enhancement", "cancel-enhancement", "download-enhancement", "recover-enhancement",
        }:
            job_id = document.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "job_id is required", field_paths=("job_id",))
            operation = {
                "poll-enhancement": service.poll_enhancement,
                "cancel-enhancement": service.cancel_enhancement,
                "download-enhancement": service.download_enhancement,
                "recover-enhancement": service.recover_enhancement,
            }[command]
            result = operation(job_id, now=now)
        else:
            raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "Unsupported command")
        return {"ok": True, "exit_code": 0, "result": result}
    except EnhancementError as error:
        return {"ok": False, "exit_code": 2, "error": error.to_dict()}
    except Exception:
        error = EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "Enhancement command failed unexpectedly")
        return {"ok": False, "exit_code": 2, "error": error.to_dict()}


def execute_enhancement(
    document: Mapping[str, object],
    *,
    adapter_name: str = "rejecting",
    adapter: object | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    if adapter_name not in {"rejecting", "fake", "runninghub"}:
        raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "Enhancement adapter selection is invalid")
    inspected = VideoEnhancementInterface().inspect_enhancement_request(document, now=now)
    raw_input = document.get("input")
    raw_profile = document.get("workflow_profile")
    if not isinstance(raw_input, Mapping) or not isinstance(raw_profile, Mapping):
        raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "Enhancement request is invalid")
    path_value = raw_input.get("path")
    if not isinstance(path_value, str):
        raise EnhancementError(EnhancementErrorCode.INPUT_FILE_INVALID, "Enhancement input path is invalid")
    workspace = Path(path_value).resolve(strict=True).parent
    ledger = RunningHubCliLedger(workspace)
    idempotency_key = str(inspected["idempotency_key"])
    request_hash = str(inspected["request_hash"])
    replay = ledger.replay(idempotency_key=idempotency_key, request_hash=request_hash)
    if replay is not None:
        return replay

    ledger.acquire()
    try:
        provider = adapter or _selected_adapter(adapter_name)
        adapter_request = {
            **snapshot(inspected),
            "input": snapshot(raw_input),
            "workflow_profile": snapshot(raw_profile),
        }
        try:
            task_id = provider.submit(adapter_request)
        except AdapterFailure as error:
            _raise_adapter_failure(error)
        if not isinstance(task_id, str) or not task_id:
            raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "Enhancement adapter returned an invalid task")
        local_status_chain = ["SUBMITTED"]
        task_cost_time: object = None
        while True:
            try:
                polled = provider.poll(task_id)
            except AdapterFailure as error:
                _raise_adapter_failure(error)
            if not isinstance(polled, Mapping):
                raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "Enhancement adapter returned invalid poll data")
            state = polled.get("state")
            if state == "running":
                local_status_chain.append("RUNNING")
                continue
            if state == "failed":
                raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "Enhancement Provider reported failure")
            if state != "succeeded":
                raise EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "Enhancement adapter returned an unsupported state")
            local_status_chain.append("SUCCEEDED")
            task_cost_time = polled.get("task_cost_time")
            break

        summary = _execution_summary(provider, task_id, local_status_chain, task_cost_time)
        pre_download = {
            "authorization_id": inspected["authorization"]["authorization_id"],
            "work_item_id": inspected["authorization"]["work_item_id"],
            "request_hash": request_hash,
            "idempotency_key": idempotency_key,
            "adapter": adapter_name,
            "state": "succeeded",
            "task_id": task_id,
            "task_cost_time": summary["task_cost_time"],
            "status_chain": summary["status_chain"],
            "workflow_id": summary["workflow_id"],
            "workflow_json_sha256": summary["workflow_json_sha256"],
            "input_file": inspected["input_summary"]["file_name"],
            "input_size_bytes": inspected["input_summary"]["size_bytes"],
            "input_sha256": inspected["input_summary"]["sha256"],
            "artifact_file": ARTIFACT_NAME,
            "receipt_file": RECEIPT_NAME,
            "output_media_type": None,
            "output_size_bytes": None,
            "output_sha256": None,
            "output_source_digest": None,
            "provider_network_performed": bool(getattr(provider, "network_performed", False)),
            "network_calls": int(getattr(provider, "network_calls", 0)),
            "replayed": False,
        }
        ledger.persist_before_download(pre_download)
        try:
            artifact = provider.download(task_id)
        except AdapterFailure as error:
            _raise_adapter_failure(error)
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("content"), bytes):
            raise EnhancementError(EnhancementErrorCode.DOWNLOAD_INTEGRITY_FAILED, "Enhancement output bytes are invalid")
        content = artifact["content"]
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if (
            not content
            or artifact.get("sha256") != actual
            or artifact.get("media_type") != "video/mp4"
            or len(content) < 12
            or content[4:8] != b"ftyp"
        ):
            raise EnhancementError(EnhancementErrorCode.DOWNLOAD_INTEGRITY_FAILED, "Enhancement output integrity check failed")
        source_uri = artifact.get("source_uri")
        if not isinstance(source_uri, str):
            raise EnhancementError(EnhancementErrorCode.DOWNLOAD_INTEGRITY_FAILED, "Enhancement output source is invalid")
        final_summary = _execution_summary(provider, task_id, local_status_chain + ["DOWNLOADED"], task_cost_time)
        receipt = {
            **pre_download,
            "state": "downloaded",
            "task_cost_time": final_summary["task_cost_time"],
            "status_chain": final_summary["status_chain"],
            "output_media_type": "video/mp4",
            "output_size_bytes": len(content),
            "output_sha256": actual,
            "output_source_digest": content_digest(source_uri),
            "network_calls": int(getattr(provider, "network_calls", 0)),
        }
        receipt["receipt_digest"] = "sha256:" + hashlib.sha256(canonical_json(receipt).encode("utf-8")).hexdigest()
        ledger.finalize(content, receipt)
        return snapshot(receipt)
    finally:
        ledger.release()


def _selected_adapter(name: str) -> object:
    if name == "runninghub":
        return RunningHubVideoEnhancementAdapter()
    if name == "fake":
        return FakeRunningHubVideoEnhancementAdapter()
    return RejectingVideoEnhancementAdapter()


def _raise_adapter_failure(error: AdapterFailure) -> None:
    code = (
        EnhancementErrorCode.CREDENTIAL_UNAVAILABLE
        if error.code == "CREDENTIAL_UNAVAILABLE"
        else EnhancementErrorCode.PROVIDER_REJECTED
    )
    raise EnhancementError(
        code,
        str(error),
        details={"adapter_code": error.code},
        retryable=False,
    ) from None


def _execution_summary(
    provider: object,
    task_id: str,
    fallback_chain: list[str],
    fallback_cost_time: object,
) -> dict[str, object]:
    method = getattr(provider, "execution_summary", None)
    if callable(method):
        summary = method(task_id)
        if isinstance(summary, Mapping):
            return {
                "task_cost_time": summary.get("task_cost_time"),
                "status_chain": list(summary.get("status_chain", fallback_chain)),
                "workflow_id": summary.get("workflow_id"),
                "workflow_json_sha256": summary.get("workflow_json_sha256"),
            }
    return {
        "task_cost_time": fallback_cost_time,
        "status_chain": list(fallback_chain),
        "workflow_id": None,
        "workflow_json_sha256": None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _JsonArgumentParser(prog="video-enhancement")
    parser.add_argument("command", choices=(
        "enhance",
        "inspect-enhancement-request",
        "submit-enhancement",
        "poll-enhancement",
        "cancel-enhancement",
        "download-enhancement",
        "recover-enhancement",
    ))
    parser.add_argument("input", help="UTF-8 JSON request file or '-' for stdin")
    parser.add_argument("--adapter", choices=("rejecting", "fake", "runninghub"))
    try:
        args = parser.parse_args(argv)
        if args.command != "enhance" and args.adapter is not None:
            raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "--adapter is only valid for enhance")
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError
        if args.command == "enhance":
            execution = execute_enhancement(document, adapter_name=args.adapter or "rejecting")
            result = {"ok": True, "exit_code": 0, "result": execution}
        else:
            result = run_cli(args.command, document)
    except EnhancementError as error:
        result = {"ok": False, "exit_code": 2, "error": error.to_dict()}
    except (OSError, ValueError, json.JSONDecodeError):
        error = EnhancementError(EnhancementErrorCode.INVALID_INPUT, "Input must be a readable UTF-8 JSON object")
        result = {"ok": False, "exit_code": 2, "error": error.to_dict()}
    print(canonical_json(result))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
