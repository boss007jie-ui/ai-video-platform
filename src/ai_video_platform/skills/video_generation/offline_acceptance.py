"""Independent offline acceptance CLI for the Video Generation workline."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket

from .adapters import FakeVideoProviderAdapter, RejectingVideoProviderAdapter
from .cli import run_cli
from .interface import VideoGenerationInterface
from .ledger import InMemoryVideoExecutionLedger
from .models import canonical_json, content_digest, snapshot
from .preflight import contains_sensitive_material


class _OfflineNetworkBlocked(RuntimeError):
    pass


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_exclusive(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def load_package(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(value, Mapping) and value.get("ok") is True and isinstance(value.get("result"), Mapping):
        value = value["result"]
    if not isinstance(value, Mapping) or value.get("artifact_name") != "VideoExecutionPackage":
        raise ValueError("input is not a VideoExecutionPackage")
    return snapshot(value)


def build_sanitized_request(
    package: Mapping[str, object],
    *,
    now: datetime,
    scenario: str = "success",
) -> dict[str, object]:
    evaluated_at = now.astimezone(timezone.utc)
    return {
        "business_sample_id": "sanitized-product-video-001",
        "execution_package": snapshot(package),
        "approval_record": {
            "approval_id": "offline-acceptance-approved",
            "approval_type": "video_generation",
            "outcome": "approved",
            "authority": {"authority_id": "authorized-approval-boundary"},
            "decided_at": _timestamp(evaluated_at - timedelta(minutes=1)),
            "decision_ref": "FT-05-001-OFFLINE-ACCEPTANCE",
            "subject_ref": {"digest": package["package_digest"]},
            "valid_until": _timestamp(evaluated_at + timedelta(hours=1)),
        },
        "budget": {
            "estimated_cost_units": 0,
            "max_cost_units": 1,
            "max_requests": 1,
            "max_concurrency": 1,
            "max_attempts": 3,
            "timeout_seconds": 60,
        },
        "provider_binding": {
            "binding_ref": "offline-fake-video",
            "provider_id": "fake-video",
            "model_id": "deterministic-offline-model",
            "credential_ref": "env://OFFLINE_FAKE_VIDEO",
        },
        "output": {
            "format": "mp4",
            "prompt": "Sanitized handheld product demonstration with a steady studio camera.",
            "resolution": "480p",
            "duration_seconds": 5,
        },
        "idempotency_key": f"ft-05-001-offline-{scenario}",
    }


def _job_id(inspected: Mapping[str, object]) -> str:
    return "job-" + content_digest({
        "request_hash": inspected["request_hash"],
        "idempotency_key": inspected["idempotency_key"],
    }).removeprefix("sha256:")[:20]


def _history(ledger: InMemoryVideoExecutionLedger, job_id: str) -> list[str]:
    return [str(item["state"]) for item in ledger.get(job_id)["history"]]


@contextmanager
def _network_denied(attempts: list[str]):
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked_connect(*args, **kwargs):
        del args, kwargs
        attempts.append("socket.connect")
        raise _OfflineNetworkBlocked("Offline acceptance network access is blocked")

    def blocked_create_connection(*args, **kwargs):
        del args, kwargs
        attempts.append("socket.create_connection")
        raise _OfflineNetworkBlocked("Offline acceptance network access is blocked")

    socket.socket.connect = blocked_connect
    socket.create_connection = blocked_create_connection
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create_connection


def run_acceptance(
    package: Mapping[str, object],
    *,
    evidence_dir: Path,
    now: datetime | None = None,
) -> dict[str, object]:
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if contains_sensitive_material(package):
        raise ValueError("VideoExecutionPackage contains forbidden sensitive material")
    base_request = build_sanitized_request(package, now=evaluated_at)
    VideoGenerationInterface().inspect_video_request(base_request, now=evaluated_at)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    _write_json_exclusive(evidence_dir / "sanitized-business-request.json", base_request)

    success_adapter = FakeVideoProviderAdapter(poll_states=("running", "succeeded"))
    success_ledger = InMemoryVideoExecutionLedger()
    success_interface = VideoGenerationInterface(adapter=success_adapter, ledger=success_ledger)
    rejecting_adapter = RejectingVideoProviderAdapter()
    rejecting_ledger = InMemoryVideoExecutionLedger()
    rejecting_interface = VideoGenerationInterface(adapter=rejecting_adapter, ledger=rejecting_ledger)
    cancel_adapter = FakeVideoProviderAdapter(poll_states=("running",))
    cancel_ledger = InMemoryVideoExecutionLedger()
    cancel_interface = VideoGenerationInterface(adapter=cancel_adapter, ledger=cancel_ledger)
    recovery_adapter = FakeVideoProviderAdapter(poll_failures=3)
    recovery_ledger = InMemoryVideoExecutionLedger()
    recovery_interface = VideoGenerationInterface(adapter=recovery_adapter, ledger=recovery_ledger)
    network_attempts: list[str] = []
    with _network_denied(network_attempts):
        inspected = run_cli("inspect-video-request", base_request, now=evaluated_at, interface=success_interface)
        submitted = run_cli("submit-video", base_request, now=evaluated_at, interface=success_interface)
        success_job_id = str(submitted["result"]["job_id"])
        first_poll = run_cli("poll-video", {"job_id": success_job_id}, now=evaluated_at, interface=success_interface)
        second_poll = run_cli("poll-video", {"job_id": success_job_id}, now=evaluated_at, interface=success_interface)
        downloaded = run_cli("download-video", {"job_id": success_job_id}, now=evaluated_at, interface=success_interface)

        rejecting_request = build_sanitized_request(package, now=evaluated_at, scenario="rejecting")
        rejecting_inspected = run_cli("inspect-video-request", rejecting_request, now=evaluated_at, interface=rejecting_interface)
        rejecting = run_cli("submit-video", rejecting_request, now=evaluated_at, interface=rejecting_interface)
        rejecting_job_id = _job_id(rejecting_inspected["result"])

        cancel_request = build_sanitized_request(package, now=evaluated_at, scenario="cancel")
        cancel_submitted = run_cli("submit-video", cancel_request, now=evaluated_at, interface=cancel_interface)
        cancel_job_id = str(cancel_submitted["result"]["job_id"])
        cancelled = run_cli("cancel-video", {"job_id": cancel_job_id}, now=evaluated_at, interface=cancel_interface)
        recovered_cancel = run_cli(
            "recover-video",
            {"job_id": cancel_job_id},
            now=evaluated_at,
            interface=VideoGenerationInterface(adapter=FakeVideoProviderAdapter(), ledger=cancel_ledger),
        )

        recovery_request = build_sanitized_request(package, now=evaluated_at, scenario="recovery")
        recovery_submitted = run_cli("submit-video", recovery_request, now=evaluated_at, interface=recovery_interface)
        recovery_job_id = str(recovery_submitted["result"]["job_id"])
        failed_poll = run_cli("poll-video", {"job_id": recovery_job_id}, now=evaluated_at, interface=recovery_interface)
        recovered_poll = run_cli(
            "recover-video",
            {"job_id": recovery_job_id},
            now=evaluated_at,
            interface=VideoGenerationInterface(adapter=FakeVideoProviderAdapter(), ledger=recovery_ledger),
        )

    success_chain = _history(success_ledger, success_job_id)
    rejecting_chain = _history(rejecting_ledger, rejecting_job_id)
    cancel_chain = _history(cancel_ledger, cancel_job_id)
    recovery_chain = _history(recovery_ledger, recovery_job_id)
    all_adapters = (success_adapter, rejecting_adapter, cancel_adapter, recovery_adapter)
    checks = {
        "fake_commands_ok": all(item["ok"] for item in (inspected, submitted, first_poll, second_poll, downloaded)),
        "fake_ledger_complete": success_chain == ["submitting", "submitted", "polling", "succeeded", "downloaded"],
        "rejecting_failed_closed": rejecting.get("ok") is False and rejecting_chain == ["submitting", "failed"],
        "cancel_recovered": cancelled.get("ok") is True and recovered_cancel.get("ok") is True and cancel_chain == ["submitting", "submitted", "cancelled"],
        "poll_recovered": failed_poll.get("ok") is False and recovered_poll.get("ok") is True and recovery_chain == ["submitting", "submitted", "recovery_required"],
        "adapter_network_zero": all(
            getattr(adapter, "network_performed", True) is False and getattr(adapter, "network_calls", 1) == 0
            for adapter in all_adapters
        ),
        "socket_network_zero": not network_attempts,
    }
    receipt = {
        "authorization_id": "FTG-0-20260720-001",
        "work_item_id": "FT-05-001",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "provider_network_performed": not checks["adapter_network_zero"] or not checks["socket_network_zero"],
        "business_sample_id": base_request["business_sample_id"],
        "fake_success": {
            "commands": [inspected, submitted, first_poll, second_poll, downloaded],
            "ledger_state_chain": success_chain,
        },
        "rejecting_fail_closed": {
            "result": rejecting,
            "ledger_state_chain": rejecting_chain,
            "provider_network_performed": not checks["adapter_network_zero"],
        },
        "cancel_recovery": {
            "cancelled": cancelled,
            "recovered": recovered_cancel,
            "ledger_state_chain": cancel_chain,
        },
        "poll_recovery": {
            "failed_poll": failed_poll,
            "recovered": recovered_poll,
            "ledger_state_chain": recovery_chain,
        },
        "finished_at": _timestamp(evaluated_at),
    }
    _write_json_exclusive(evidence_dir / "offline-acceptance-receipt.json", receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = None
    try:
        args = _parser().parse_args(argv)
        receipt = run_acceptance(load_package(args.package), evidence_dir=args.evidence_dir)
        exit_code = 0 if receipt["status"] == "PASS" else 2
    except _OfflineNetworkBlocked:
        receipt = {
            "authorization_id": "FTG-0-20260720-001",
            "work_item_id": "FT-05-001",
            "status": "FAIL",
            "error_code": "OFFLINE_NETWORK_BLOCKED",
            "provider_network_performed": False,
            "provider_network_attempted": True,
            "network_blocked": True,
            "checks": {"socket_network_zero": False},
        }
        if args is not None and args.evidence_dir.is_dir():
            try:
                _write_json_exclusive(args.evidence_dir / "offline-acceptance-receipt.json", receipt)
            except OSError:
                pass
        exit_code = 2
    except (OSError, ValueError, KeyError, TypeError):
        receipt = {
            "authorization_id": "FTG-0-20260720-001",
            "work_item_id": "FT-05-001",
            "status": "FAIL",
            "error_code": "OFFLINE_ACCEPTANCE_REJECTED",
        }
        exit_code = 2
    print(canonical_json(receipt))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
