"""Provider-free offline acceptance for the Video Enhancement skill."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
from typing import Sequence

from .adapters import FakeVideoEnhancementAdapter, RejectingVideoEnhancementAdapter
from .cli import run_cli
from .interface import VideoEnhancementInterface
from .ledger import InMemoryEnhancementLedger
from .models import canonical_json, content_digest
from .preflight import fake_workflow_profile


SYNTHETIC_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomft-05-002-synthetic"


class OfflineNetworkBlocked(RuntimeError):
    pass


def _write_json_exclusive(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _request(media: Path, scenario: str) -> dict[str, object]:
    return {
        "authorization": {"authorization_id": "FTG-0-20260720-001", "work_item_id": "FT-05-002"},
        "input": {
            "path": str(media),
            "file_name": media.name,
            "size_bytes": len(SYNTHETIC_MP4),
            "sha256": "sha256:" + hashlib.sha256(SYNTHETIC_MP4).hexdigest(),
            "duration_seconds": 5,
            "width": 640,
            "height": 360,
            "fps": 30,
            "rights": {
                "basis": "SYNTHETIC",
                "lifecycle": "provider_eligible",
                "source_class": "synthetic_fixture",
                "fixture_provenance": "generated_for_ft_05_002_offline_acceptance",
            },
        },
        "workflow_profile": fake_workflow_profile(),
        "operations": [
            {"type": "upscale", "factor": 2},
            {"type": "frame_interpolation", "factor": 2},
            {"type": "denoise_restore", "strength": 0.2},
        ],
        "budget": {
            "max_cost_usd": 0.02,
            "max_requests": 1,
            "max_concurrency": 1,
            "max_attempts": 3,
            "timeout_seconds": 120,
        },
        "idempotency_key": f"ft-05-002-offline-{scenario}",
    }


@contextmanager
def _network_denied(attempts: list[str]):
    original_connect = socket.socket.connect
    original_create = socket.create_connection

    def blocked(*args, **kwargs):
        del args, kwargs
        attempts.append("socket")
        raise OfflineNetworkBlocked("offline acceptance blocked network access")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create


def _chain(ledger: InMemoryEnhancementLedger, job_id: str) -> list[str]:
    return [str(item["state"]) for item in ledger.get(job_id)["history"]]


def run_acceptance(*, evidence_dir: Path, now: datetime | None = None) -> dict[str, object]:
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    media = evidence_dir / "synthetic-owned-fixture.mp4"
    media.write_bytes(SYNTHETIC_MP4)
    sample = {
        "business_sample_id": "sanitized-video-enhancement-001",
        "input": {
            "file_name": media.name,
            "size_bytes": len(SYNTHETIC_MP4),
            "sha256": "sha256:" + hashlib.sha256(SYNTHETIC_MP4).hexdigest(),
            "rights_basis": "SYNTHETIC",
        },
        "operations": ["upscale", "frame_interpolation", "denoise_restore"],
        "provider_network_performed": False,
    }
    _write_json_exclusive(evidence_dir / "sanitized-business-sample.json", sample)

    success_adapter = FakeVideoEnhancementAdapter(poll_states=("running", "succeeded"))
    success_ledger = InMemoryEnhancementLedger()
    success = VideoEnhancementInterface(adapter=success_adapter, ledger=success_ledger)
    reject_adapter = RejectingVideoEnhancementAdapter()
    reject_ledger = InMemoryEnhancementLedger()
    rejecting = VideoEnhancementInterface(adapter=reject_adapter, ledger=reject_ledger)
    cancel_adapter = FakeVideoEnhancementAdapter(poll_states=("running",))
    cancel_ledger = InMemoryEnhancementLedger()
    cancelling = VideoEnhancementInterface(adapter=cancel_adapter, ledger=cancel_ledger)
    recover_adapter = FakeVideoEnhancementAdapter(poll_failures=3)
    recover_ledger = InMemoryEnhancementLedger()
    recovering = VideoEnhancementInterface(adapter=recover_adapter, ledger=recover_ledger)
    attempts: list[str] = []
    with _network_denied(attempts):
        request = _request(media, "success")
        inspect = run_cli("inspect-enhancement-request", request, now=evaluated_at, interface=success)
        submit = run_cli("submit-enhancement", request, now=evaluated_at, interface=success)
        job_id = str(submit["result"]["job_id"])
        poll_1 = run_cli("poll-enhancement", {"job_id": job_id}, now=evaluated_at, interface=success)
        poll_2 = run_cli("poll-enhancement", {"job_id": job_id}, now=evaluated_at, interface=success)
        download = run_cli("download-enhancement", {"job_id": job_id}, now=evaluated_at, interface=success)

        rejected = run_cli("submit-enhancement", _request(media, "reject"), now=evaluated_at, interface=rejecting)
        reject_job = "enh-" + content_digest({
            "request_hash": run_cli("inspect-enhancement-request", _request(media, "reject"), now=evaluated_at)["result"]["request_hash"],
            "idempotency_key": "ft-05-002-offline-reject",
        }).removeprefix("sha256:")[:20]

        cancel_submit = run_cli("submit-enhancement", _request(media, "cancel"), now=evaluated_at, interface=cancelling)
        cancel_job = str(cancel_submit["result"]["job_id"])
        cancelled = run_cli("cancel-enhancement", {"job_id": cancel_job}, now=evaluated_at, interface=cancelling)
        cancel_recovered = run_cli("recover-enhancement", {"job_id": cancel_job}, now=evaluated_at, interface=cancelling)

        recover_submit = run_cli("submit-enhancement", _request(media, "recover"), now=evaluated_at, interface=recovering)
        recover_job = str(recover_submit["result"]["job_id"])
        poll_failed = run_cli("poll-enhancement", {"job_id": recover_job}, now=evaluated_at, interface=recovering)
        recovered = run_cli("recover-enhancement", {"job_id": recover_job}, now=evaluated_at, interface=recovering)

    adapters = (success_adapter, reject_adapter, cancel_adapter, recover_adapter)
    success_chain = _chain(success_ledger, job_id)
    reject_chain = _chain(reject_ledger, reject_job)
    cancel_chain = _chain(cancel_ledger, cancel_job)
    recover_chain = _chain(recover_ledger, recover_job)
    checks = {
        "six_cli_commands": all(item["ok"] for item in (inspect, submit, poll_1, poll_2, download, cancelled, cancel_recovered, recovered)),
        "fake_lifecycle": success_chain == ["submitting", "submitted", "polling", "succeeded", "downloaded"],
        "rejecting_fail_closed": rejected["ok"] is False and reject_chain == ["submitting", "failed"],
        "cancel_recovery": cancel_chain == ["submitting", "submitted", "cancelled"],
        "poll_recovery": poll_failed["ok"] is False and recover_chain == ["submitting", "submitted", "recovery_required"],
        "provider_network_zero": not attempts and all(getattr(item, "network_calls", 1) == 0 for item in adapters),
    }
    receipt = {
        "authorization_id": "FTG-0-20260720-001",
        "work_item_id": "FT-05-002",
        "business_sample_id": sample["business_sample_id"],
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "provider_network_performed": False,
        "fake_success": {"ledger_state_chain": success_chain, "receipt": download["result"]["receipt"]},
        "rejecting_fail_closed": {"ledger_state_chain": reject_chain, "result": rejected},
        "cancel_recovery": {"ledger_state_chain": cancel_chain, "receipt": cancelled["result"]["receipt"]},
        "poll_recovery": {"ledger_state_chain": recover_chain, "result": poll_failed, "recovered": recovered},
        "finished_at": evaluated_at.isoformat().replace("+00:00", "Z"),
    }
    _write_json_exclusive(evidence_dir / "offline-acceptance-receipt.json", receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        receipt = run_acceptance(evidence_dir=args.evidence_dir)
        code = 0 if receipt["status"] == "PASS" else 2
    except (OSError, ValueError, KeyError, TypeError, OfflineNetworkBlocked):
        receipt = {
            "authorization_id": "FTG-0-20260720-001",
            "work_item_id": "FT-05-002",
            "status": "FAIL",
            "error_code": "OFFLINE_ACCEPTANCE_REJECTED",
            "provider_network_performed": False,
        }
        code = 2
    print(canonical_json(receipt))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
