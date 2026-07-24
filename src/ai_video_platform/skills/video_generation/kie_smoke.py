"""One-shot controller for the explicitly authorized KIE Revision D smoke."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from .adapters import AdapterFailure
from .interface import VideoGenerationInterface
from .kie_adapter import KieCredentialResolver, KieReferenceImageUploader, KieVideoProviderAdapter, UrllibKieHttpTransport
from .ledger import InMemoryVideoExecutionLedger


AUTHORIZATION_ID = "FTG-P-VIDEO-002"
WORK_ITEM_ID = "FT-05-001"
MODEL_ID = "bytedance/seedance-2-fast"
PROMPT = (
    "A clean commercial product study of the exact handheld laser device shown in the reference images. "
    "Begin with the full side profile, then make one subtle push-in toward the front emitter and tail button. "
    "Preserve the exact product proportions, colors, labels, emitter shape, and tail-button geometry. "
    "Neutral dark studio background, controlled reflections, steady camera, no people, no text overlays."
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_event(path: Path, *, event: str, at: datetime, **details: object) -> None:
    safe = {"at": _timestamp(at), "event": event, **details}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(safe, ensure_ascii=False, sort_keys=True) + "\n")


def _redact_exact_credential(value: object, credential: str) -> object:
    if isinstance(value, Mapping):
        return {str(key): _redact_exact_credential(nested, credential) for key, nested in value.items()}
    if isinstance(value, list):
        return [_redact_exact_credential(item, credential) for item in value]
    if isinstance(value, str):
        return value.replace(credential, "[REDACTED]")
    return value


def _finalize_secret_scan(
    evidence_dir: Path,
    pending_result: Mapping[str, object],
    resolver: KieCredentialResolver,
) -> dict[str, object]:
    """Redact exact credential material and fail closed unless the final scan is zero."""
    try:
        credential = resolver.resolve()
    except AdapterFailure:
        safe = dict(pending_result)
        safe["secret_scan_status"] = "NOT_RUN"
        safe["secret_scan_matches"] = None
        if safe.get("provider_smoke") == "PASS":
            safe["provider_smoke"] = "FAIL"
            safe["error_type"] = "SecretScanFailure"
            safe["provider_error_summary"] = "Credential scan was unavailable and failed closed"
        return safe
    needle = credential.encode("utf-8")
    serialized = json.dumps(pending_result, ensure_ascii=False, sort_keys=True).encode("utf-8")
    detected = serialized.count(needle)
    safe_value = _redact_exact_credential(pending_result, credential)
    safe = dict(safe_value) if isinstance(safe_value, Mapping) else {}
    scan_error = False
    for path in evidence_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            content = path.read_bytes()
            found = content.count(needle)
            detected += found
            if found:
                path.write_bytes(content.replace(needle, b"[REDACTED]"))
        except OSError:
            scan_error = True
    remaining = json.dumps(safe, ensure_ascii=False, sort_keys=True).encode("utf-8").count(needle)
    if not scan_error:
        for path in evidence_dir.rglob("*"):
            if path.is_file():
                try:
                    remaining += path.read_bytes().count(needle)
                except OSError:
                    scan_error = True
                    break
    safe["secret_scan_status"] = "ERROR" if scan_error else ("PASS" if remaining == 0 else "FAIL")
    safe["secret_scan_matches"] = None if scan_error else remaining
    if detected or scan_error or remaining:
        safe["provider_smoke"] = "FAIL"
        safe["error_type"] = "SecretScanFailure"
        safe["secret_scan_failure_code"] = (
            "SCAN_ERROR" if scan_error else "CREDENTIAL_MATERIAL_DETECTED"
        )
        safe.setdefault("provider_error_summary", "Credential evidence scan failed closed")
    return safe


def _default_reservation_path() -> Path:
    return Path(__file__).resolve().parent / "evidence" / "ftg-p-video-002-revision-d-reservation.json"


def load_execution_package(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(value, Mapping) and value.get("ok") is True and isinstance(value.get("result"), Mapping):
        value = value["result"]
    if not isinstance(value, Mapping) or value.get("artifact_name") != "VideoExecutionPackage":
        raise ValueError("planning input is not a VideoExecutionPackage")
    return dict(value)


def validate_reference_digests(package: Mapping[str, object], expected_sha256: Sequence[str]) -> None:
    mappings = package.get("asset_mapping")
    if not isinstance(mappings, list):
        raise ValueError("VideoExecutionPackage asset mapping is unavailable")
    approved = {
        item.get("sha256")
        for item in mappings
        if isinstance(item, Mapping) and isinstance(item.get("sha256"), str)
    }
    if len(expected_sha256) < 2 or len(set(expected_sha256)) != len(expected_sha256):
        raise ValueError("at least two distinct approved reference digests are required")
    if any(value not in approved for value in expected_sha256):
        raise ValueError("reference digest is not approved by the VideoExecutionPackage")


def build_smoke_request(
    package: Mapping[str, object],
    reference_urls: Sequence[str],
    *,
    now: datetime,
) -> dict[str, object]:
    if len(reference_urls) < 2:
        raise ValueError("at least two uploaded reference URLs are required")
    decided_at = now.astimezone(timezone.utc)
    return {
        "execution_package": dict(package),
        "approval_record": {
            "approval_id": "ftg-p-video-002-revision-d",
            "approval_type": "video_generation",
            "outcome": "approved",
            "authority": {"authority_id": "authorized-approval-boundary"},
            "decided_at": _timestamp(decided_at),
            "decision_ref": "FTG-P-VIDEO-002-REVISION-D",
            "subject_ref": {"digest": package["artifact_digest"]},
            "valid_until": _timestamp(decided_at + timedelta(minutes=30)),
        },
        "budget": {
            "estimated_cost_units": 100,
            "max_cost_units": 100,
            "max_requests": 1,
            "max_concurrency": 1,
            "max_attempts": 2,
            "timeout_seconds": 1800,
        },
        "provider_binding": {
            "binding_ref": "ftg-p-video-002-revision-d",
            "provider_id": "kie",
            "model_id": MODEL_ID,
            "credential_ref": "env://KIE_API_KEY",
        },
        "output": {
            "format": "mp4",
            "prompt": PROMPT,
            "reference_image_urls": list(reference_urls),
            "resolution": "480p",
            "aspect_ratio": "16:9",
            "duration": 5,
            "return_last_frame": False,
            "generate_audio": False,
            "web_search": False,
        },
        "idempotency_key": "ftg-p-video-002-revision-d-20260722",
    }


def run_smoke(
    *,
    package_path: Path,
    reference_paths: Sequence[Path],
    reference_sha256: Sequence[str],
    evidence_dir: Path,
    poll_interval_seconds: float = 10.0,
) -> dict[str, object]:
    if len(reference_paths) != len(reference_sha256):
        raise ValueError("reference paths and digests must have equal length")
    package = load_execution_package(package_path)
    validate_reference_digests(package, reference_sha256)
    resolver = KieCredentialResolver()
    resolver.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    started_at = _utc_now()
    global_reservation = _default_reservation_path()
    global_reservation.parent.mkdir(parents=True, exist_ok=True)
    with global_reservation.open("x", encoding="utf-8") as stream:
        json.dump({
            "authorization_id": AUTHORIZATION_ID,
            "work_item_id": WORK_ITEM_ID,
            "revision": "D",
            "started_at": _timestamp(started_at),
            "state": "ATTEMPT_RESERVED",
        }, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    attempt_path = evidence_dir / "provider-attempt.json"
    with attempt_path.open("x", encoding="utf-8") as stream:
        json.dump({
            "authorization_id": AUTHORIZATION_ID,
            "work_item_id": WORK_ITEM_ID,
            "revision": "D",
            "started_at": _timestamp(started_at),
            "state": "ATTEMPT_RESERVED",
        }, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    events_path = evidence_dir / "provider-events.jsonl"
    result_path = evidence_dir / "provider-result.json"
    transport = UrllibKieHttpTransport(timeout_seconds=30.0)
    uploader = KieReferenceImageUploader(transport=transport, credential_resolver=resolver)
    ledger = InMemoryVideoExecutionLedger()
    adapter = KieVideoProviderAdapter(transport=transport, credential_resolver=resolver)
    interface = VideoGenerationInterface(adapter=adapter, ledger=ledger)
    submitted_job_id: str | None = None
    task_id: str | None = None
    generation_submissions = 0
    try:
        uploaded_urls: list[str] = []
        for image_path, expected in zip(reference_paths, reference_sha256, strict=True):
            uploaded_urls.append(uploader.upload(image_path, expected_sha256=expected))
        _append_event(events_path, event="references_uploaded", at=_utc_now(), count=len(uploaded_urls))
        request = build_smoke_request(package, uploaded_urls, now=_utc_now())
        interface.inspect_video_request(request, now=_utc_now())
        generation_submissions += 1
        submitted = interface.submit_video(request, now=_utc_now())
        submitted_job_id = str(submitted["job_id"])
        task_id = str(ledger.get(submitted_job_id)["provider_job_id"])
        _append_event(events_path, event="submitted", at=_utc_now(), task_id=task_id)
        while True:
            polled = interface.poll_video(submitted_job_id, now=_utc_now())
            _append_event(
                events_path,
                event="poll",
                at=_utc_now(),
                state=polled["state"],
                provider_cost_units=polled.get("provider_cost_units"),
            )
            if polled["state"] == "succeeded":
                break
            if polled["state"] != "polling":
                raise AdapterFailure(
                    "KIE_PROVIDER_FAILED",
                    "KIE smoke reached a non-success terminal state",
                    retryable=False,
                    http_status=polled.get("provider_http_status"),
                    provider_error_summary=polled.get("provider_error_summary"),
                )
            time.sleep(poll_interval_seconds)
        downloaded = interface.download_video(submitted_job_id, now=_utc_now())
        manifest = downloaded["asset_manifest_request"]
        record = ledger.get(submitted_job_id)
        result = {
            "authorization_id": AUTHORIZATION_ID,
            "work_item_id": WORK_ITEM_ID,
            "revision": "D",
            "provider_smoke": "PASS",
            "task_id": task_id,
            "generation_submissions": generation_submissions,
            "ledger_state_chain": [item["state"] for item in record["history"]],
            "artifact_uri": manifest["uri"],
            "size_bytes": manifest["size_bytes"],
            "sha256": manifest["sha256"],
            "credits_consumed": record.get("provider_cost_units"),
            "http_status": transport.http_status_chain[-1] if transport.http_status_chain else None,
            "http_status_chain": list(transport.http_status_chain),
            "download_http_status_chain": list(downloaded.get("download_http_status_chain", [])),
            "download_attempts": list(downloaded.get("download_attempts", [])),
            "download_http_status_chain_provenance": "CAPTURED_BY_REVISION_D_CONTROLLER",
            "contract_status": manifest["contract_status"],
            "finished_at": _timestamp(_utc_now()),
        }
        result = _finalize_secret_scan(evidence_dir, result, resolver)
        _write_json(result_path, result)
        if result["provider_smoke"] != "PASS":
            raise AdapterFailure(
                "SECRET_SCAN_FAILED",
                "Credential evidence scan failed closed",
                retryable=False,
            )
        return result
    except Exception as error:
        if result_path.exists():
            raise
        record = ledger.get(submitted_job_id) if submitted_job_id is not None else None
        http_status = getattr(error, "http_status", None)
        provider_error_summary = getattr(error, "provider_error_summary", None)
        details = getattr(error, "details", None)
        if isinstance(details, Mapping):
            http_status = details.get("http_status", http_status)
            provider_error_summary = details.get("provider_error_summary", provider_error_summary)
        result = {
            "authorization_id": AUTHORIZATION_ID,
            "work_item_id": WORK_ITEM_ID,
            "revision": "D",
            "provider_smoke": "FAIL",
            "task_id": task_id,
            "generation_submissions": generation_submissions,
            "ledger_state_chain": [item["state"] for item in record["history"]] if record else [],
            "artifact_uri": None,
            "size_bytes": None,
            "sha256": None,
            "credits_consumed": record.get("provider_cost_units") if record else None,
            "error_type": type(error).__name__,
            "http_status": http_status,
            "http_status_chain": list(transport.http_status_chain),
            "download_http_status_chain": (
                list(details.get("download_http_status_chain", []))
                if isinstance(details, Mapping)
                else list(adapter.download_http_status_chain)
            ),
            "download_attempts": (
                list(details.get("download_attempts", []))
                if isinstance(details, Mapping)
                else list(adapter.download_attempts)
            ),
            "download_http_status_chain_provenance": "CAPTURED_BY_REVISION_D_CONTROLLER",
            "provider_error_summary": provider_error_summary,
            "late_artifact_download_performed": False,
            "artifact_uri_valid": False,
            "finished_at": _timestamp(_utc_now()),
        }
        result = _finalize_secret_scan(evidence_dir, result, resolver)
        _write_json(result_path, result)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="perform the one authorized real smoke")
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--reference-path", action="append", required=True, type=Path)
    parser.add_argument("--reference-sha256", action="append", required=True)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    package = load_execution_package(args.package)
    validate_reference_digests(package, args.reference_sha256)
    if not args.execute:
        print(json.dumps({
            "authorization_id": AUTHORIZATION_ID,
            "work_item_id": WORK_ITEM_ID,
            "status": "DRY_RUN_READY",
            "reference_count": len(args.reference_path),
            "generation_submissions": 0,
        }, sort_keys=True))
        return 0
    result = run_smoke(
        package_path=args.package,
        reference_paths=args.reference_path,
        reference_sha256=args.reference_sha256,
        evidence_dir=args.evidence_dir,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
