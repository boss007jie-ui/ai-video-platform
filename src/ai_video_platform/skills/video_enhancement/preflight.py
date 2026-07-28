"""Pure preflight for local video enhancement inputs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any

from .errors import EnhancementError, EnhancementErrorCode, contains_sensitive_text
from .models import CONTRACT_STATUS, SCHEMA_VERSION, content_digest, snapshot


MAX_INPUT_BYTES = 30 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
ALLOWED_RIGHTS = {"OWNED", "SYNTHETIC"}
DENIED_LIFECYCLES = {"internal_analysis_only"}
ALLOWED_SOURCE_BY_RIGHTS = {"OWNED": "owned_fixture", "SYNTHETIC": "synthetic_fixture"}
DENIED_TIKTOK_FILE_NAMES = {
    "7665115424106892566.mp4",
    "7663913413235559698.mp4",
    "7655273792406637855.mp4",
}
DENIED_TIKTOK_DIGESTS = {
    "sha256:ca1c2896b7e675fb77eef61d004ffc03d6dffc568ce3edd694359033004cba11",
    "sha256:b4e5a631bb3582be07a8abd22f3cd26d1c12e2d20b4ec898238632bdfaeec1c5",
    "sha256:c13b6c53f551e1ca30aeb946ff05eb82b70167ae97770cc03202cb016a7ff681",
}
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RUNNINGHUB_AI_APP_PROFILE_ID = "runninghub-ai-app-video-enhance-v1"
RUNNINGHUB_AI_APP_ID = "2066340206713851905"
RUNNINGHUB_AI_APP_INPUT_NODE_ID = "16"
RUNNINGHUB_AI_APP_INPUT_FIELD_NAME = "video"
RUNNINGHUB_AI_APP_RESOLUTION_NODE_ID = "84"
RUNNINGHUB_AI_APP_RESOLUTION_FIELD_NAME = "value"
RUNNINGHUB_AI_APP_RESOLUTION_VALUE = "1080"
RUNNINGHUB_AI_APP_BASE_URL = "https://www.runninghub.cn/openapi/v2"


def fake_workflow_profile(profile_id: str = "fake-enhancement-profile") -> dict[str, object]:
    durations = {"fake-enhancement-profile": 10, "fake-enhancement-long-profile": 30}
    if profile_id not in durations:
        raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "offline Fake workflow profile is not approved")
    body = {
        "profile_id": profile_id,
        "profile_version": "1.0.0",
        "provider_kind": "offline_fake",
        "supported_operations": ["upscale", "frame_interpolation", "denoise_restore"],
        "operation_limits": {
            "upscale_factors": [2, 4],
            "frame_interpolation_factors": [2],
            "denoise_strength_min": 0.0,
            "denoise_strength_max": 1.0,
        },
        "media_limits": {
            "max_duration_seconds": durations[profile_id],
            "max_width": 1920,
            "max_height": 1080,
            "max_fps": 60,
        },
        "execution_limits": {
            "max_requests": 2,
            "max_concurrency": 1,
            "max_attempts": 3,
            "max_timeout_seconds": 120,
            "max_runtime_seconds": 60,
        },
        "rate_snapshot": {
            "snapshot_at": "2026-07-22T00:00:00Z",
            "instance_type": "standard-24gb",
            "currency": "USD",
            "rate_per_hour": 0.70,
            "public_source": "RunningHub Enterprise Shared public page",
            "estimate_only": True,
            "not_a_quote": True,
        },
    }
    return snapshot({**body, "profile_digest": content_digest(body)})


def runninghub_workflow_profile(
    *,
    workflow_id: str,
    workflow_json_sha256: str,
    input_node_id: str,
    input_field_name: str,
    node_info_list: list[dict[str, object]],
    output_origins: list[str],
) -> dict[str, object]:
    """Build a digest-bound profile from an externally approved workflow binding."""

    body = {
        "profile_id": "runninghub-" + workflow_id,
        "profile_version": "1.0.0",
        "provider_kind": "runninghub",
        "supported_operations": ["upscale", "frame_interpolation", "denoise_restore"],
        "operation_limits": {
            "upscale_factors": [2, 4],
            "frame_interpolation_factors": [2],
            "denoise_strength_min": 0.0,
            "denoise_strength_max": 1.0,
        },
        "media_limits": {
            "max_duration_seconds": 30,
            "max_width": 4096,
            "max_height": 4096,
            "max_fps": 120,
        },
        "execution_limits": {
            "max_requests": 1,
            "max_concurrency": 1,
            "max_attempts": 1,
            "max_timeout_seconds": 600,
            "max_runtime_seconds": 600,
        },
        "rate_snapshot": {
            "snapshot_at": "2026-07-22T00:00:00Z",
            "instance_type": "unfixed",
            "currency": "USD",
            "rate_per_hour": 0.70,
            "public_source": "RunningHub Enterprise Shared public page",
            "estimate_only": True,
            "not_a_quote": True,
        },
        "workflow_binding": {
            "workflow_id": workflow_id,
            "workflow_json_sha256": workflow_json_sha256,
            "input_node_id": input_node_id,
            "input_field_name": input_field_name,
            "node_info_list": node_info_list,
            "output_origins": output_origins,
        },
    }
    return snapshot({**body, "profile_digest": content_digest(body)})


def runninghub_ai_app_profile() -> dict[str, object]:
    """Return the fixed approved RunningHub AI application profile."""

    body = {
        "profile_id": RUNNINGHUB_AI_APP_PROFILE_ID,
        "profile_version": "1.0.0",
        "provider_kind": "runninghub",
        "provider_mode": "ai_app",
        "supported_operations": ["upscale", "frame_interpolation", "denoise_restore"],
        "operation_limits": {
            "upscale_factors": [2, 4],
            "frame_interpolation_factors": [2],
            "denoise_strength_min": 0.0,
            "denoise_strength_max": 1.0,
        },
        "media_limits": {
            "max_duration_seconds": 30,
            "max_width": 4096,
            "max_height": 4096,
            "max_fps": 120,
        },
        "execution_limits": {
            "max_requests": 1,
            "max_concurrency": 1,
            "max_attempts": 1,
            "max_timeout_seconds": 600,
            "max_runtime_seconds": 600,
        },
        "rate_snapshot": {
            "snapshot_at": "2026-07-22T00:00:00Z",
            "instance_type": "unfixed",
            "currency": "USD",
            "rate_per_hour": 0.70,
            "public_source": "RunningHub Enterprise Shared public page",
            "estimate_only": True,
            "not_a_quote": True,
        },
        "ai_app_binding": {
            "app_id": RUNNINGHUB_AI_APP_ID,
            "input_node_id": RUNNINGHUB_AI_APP_INPUT_NODE_ID,
            "input_field_name": RUNNINGHUB_AI_APP_INPUT_FIELD_NAME,
            "resolution_node_id": RUNNINGHUB_AI_APP_RESOLUTION_NODE_ID,
            "resolution_field_name": RUNNINGHUB_AI_APP_RESOLUTION_FIELD_NAME,
            "resolution_value": RUNNINGHUB_AI_APP_RESOLUTION_VALUE,
            "base_url": RUNNINGHUB_AI_APP_BASE_URL,
        },
    }
    return snapshot({**body, "profile_digest": content_digest(body)})


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, f"{field} must be an object", field_paths=(field,))
    try:
        return snapshot(value)
    except (TypeError, ValueError):
        raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, f"{field} must contain finite JSON values", field_paths=(field,)) from None


def _string(value: Mapping[str, object], field: str, code: EnhancementErrorCode) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise EnhancementError(code, f"{field} is required", field_paths=(field,))
    return item


def _positive_number(value: object, field: str, code: EnhancementErrorCode) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise EnhancementError(code, f"{field} must be positive", field_paths=(field,))
    return float(value)


def _positive_int(value: object, field: str, code: EnhancementErrorCode) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EnhancementError(code, f"{field} must be a positive integer", field_paths=(field,))
    return value


def _matches_container(extension: str, content: bytes) -> bool:
    if extension in {".mp4", ".mov"}:
        return len(content) >= 12 and content[4:8] == b"ftyp"
    if extension == ".avi":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"AVI "
    return extension == ".mkv" and content.startswith(b"\x1aE\xdf\xa3")


class EnhancementPreflight:
    def inspect(self, request: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
        value = _mapping(request, "request")
        evaluated_at = now or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "now must be timezone-aware")
        authorization = self._authorization(value.get("authorization"))
        input_summary = self._input(value.get("input"))
        profile = self._profile(value.get("workflow_profile"))
        operations = self._operations(value.get("operations"), profile, input_summary)
        budget, cost = self._budget(value.get("budget"), profile)
        idempotency_key = _string(value, "idempotency_key", EnhancementErrorCode.IDEMPOTENCY_REQUIRED)
        if contains_sensitive_text(idempotency_key):
            raise EnhancementError(EnhancementErrorCode.IDEMPOTENCY_REQUIRED, "idempotency_key contains sensitive material")
        basis = {
            "authorization": authorization,
            "input_summary": input_summary,
            "workflow_profile": profile,
            "operations": operations,
            "budget": budget,
            "idempotency_key": idempotency_key,
        }
        return snapshot({
            "status": "ready",
            "schema_version": SCHEMA_VERSION,
            "contract_status": CONTRACT_STATUS,
            "authorization": authorization,
            "request_hash": content_digest(basis),
            "idempotency_key": idempotency_key,
            "input_summary": input_summary,
            "workflow_profile": profile,
            "operations": operations,
            "budget": budget,
            "cost_estimate": cost,
            "provider_network_performed": False,
            "provider_execution_performed": False,
        })

    @staticmethod
    def _authorization(raw: object) -> dict[str, str]:
        value = _mapping(raw, "authorization")
        if set(value) != {"authorization_id", "work_item_id"}:
            raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "authorization fields are invalid")
        if (
            value.get("authorization_id") != "FTG-0-20260720-001"
            or value.get("work_item_id") not in {"FT-05-002", "FT-05-003"}
        ):
            raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "authorization boundary is not effective")
        return {"authorization_id": str(value["authorization_id"]), "work_item_id": str(value["work_item_id"])}

    def _input(self, raw: object) -> dict[str, object]:
        value = _mapping(raw, "input")
        required = {"path", "file_name", "size_bytes", "sha256", "duration_seconds", "width", "height", "fps", "rights"}
        if set(value) != required:
            raise EnhancementError(EnhancementErrorCode.INPUT_FILE_INVALID, "input fields are invalid")
        path_text = _string(value, "path", EnhancementErrorCode.INPUT_FILE_INVALID)
        file_name = _string(value, "file_name", EnhancementErrorCode.INPUT_FILE_INVALID)
        if contains_sensitive_text(file_name):
            raise EnhancementError(EnhancementErrorCode.INPUT_FILE_INVALID, "input file name contains sensitive material")
        claimed_digest = _string(value, "sha256", EnhancementErrorCode.INPUT_DIGEST_MISMATCH).lower()
        rights = self._rights(value.get("rights"), file_name=file_name, digest=claimed_digest)
        path = Path(path_text)
        if path.name != file_name or path.is_symlink() or not path.is_file():
            raise EnhancementError(EnhancementErrorCode.INPUT_FILE_INVALID, "input must be a readable local regular file")
        extension = path.suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise EnhancementError(EnhancementErrorCode.INPUT_FILE_INVALID, "input extension is not supported")
        try:
            stat_before = path.stat()
            if stat_before.st_size > MAX_INPUT_BYTES:
                raise EnhancementError(EnhancementErrorCode.INPUT_TOO_LARGE, "input byte length exceeds 30MB")
            with path.open("rb") as stream:
                content = stream.read(MAX_INPUT_BYTES + 1)
            stat_after = path.stat()
        except OSError:
            raise EnhancementError(EnhancementErrorCode.INPUT_FILE_INVALID, "input file is unreadable") from None
        if len(content) > MAX_INPUT_BYTES:
            raise EnhancementError(EnhancementErrorCode.INPUT_TOO_LARGE, "input byte length exceeds 30MB")
        if (
            stat_before.st_size != stat_after.st_size
            or stat_before.st_mtime_ns != stat_after.st_mtime_ns
            or stat_after.st_size != len(content)
        ):
            raise EnhancementError(EnhancementErrorCode.INPUT_FILE_INVALID, "input file changed during verification")
        if not content or len(content) > MAX_INPUT_BYTES:
            code = EnhancementErrorCode.INPUT_TOO_LARGE if len(content) > MAX_INPUT_BYTES else EnhancementErrorCode.INPUT_FILE_INVALID
            raise EnhancementError(code, "input byte length is outside the allowed range")
        if value.get("size_bytes") != len(content):
            raise EnhancementError(EnhancementErrorCode.INPUT_FILE_INVALID, "declared input size does not match the local file")
        actual_digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if _DIGEST.fullmatch(claimed_digest) is None or claimed_digest != actual_digest:
            raise EnhancementError(EnhancementErrorCode.INPUT_DIGEST_MISMATCH, "declared input digest does not match the local file")
        if actual_digest in DENIED_TIKTOK_DIGESTS or not _matches_container(extension, content):
            code = EnhancementErrorCode.RIGHTS_REJECTED if actual_digest in DENIED_TIKTOK_DIGESTS else EnhancementErrorCode.INPUT_FILE_INVALID
            raise EnhancementError(code, "input is permanently excluded" if code is EnhancementErrorCode.RIGHTS_REJECTED else "input bytes do not match the declared container")
        duration = _positive_number(value.get("duration_seconds"), "duration_seconds", EnhancementErrorCode.INPUT_FILE_INVALID)
        width = _positive_int(value.get("width"), "width", EnhancementErrorCode.INPUT_FILE_INVALID)
        height = _positive_int(value.get("height"), "height", EnhancementErrorCode.INPUT_FILE_INVALID)
        fps = _positive_number(value.get("fps"), "fps", EnhancementErrorCode.INPUT_FILE_INVALID)
        return {
            "file_name": file_name,
            "format": extension.removeprefix("."),
            "size_bytes": len(content),
            "sha256": actual_digest,
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "fps": fps,
            **rights,
        }

    @staticmethod
    def _rights(raw: object, *, file_name: str, digest: str) -> dict[str, str]:
        value = _mapping(raw, "input.rights")
        required = {"basis", "lifecycle", "source_class", "fixture_provenance"}
        if set(value) != required:
            raise EnhancementError(EnhancementErrorCode.RIGHTS_REJECTED, "rights declaration is incomplete")
        basis = _string(value, "basis", EnhancementErrorCode.RIGHTS_REJECTED)
        lifecycle = _string(value, "lifecycle", EnhancementErrorCode.RIGHTS_REJECTED)
        source_class = _string(value, "source_class", EnhancementErrorCode.RIGHTS_REJECTED)
        provenance = _string(value, "fixture_provenance", EnhancementErrorCode.RIGHTS_REJECTED)
        if any(contains_sensitive_text(item) for item in (basis, lifecycle, source_class, provenance)):
            raise EnhancementError(EnhancementErrorCode.RIGHTS_REJECTED, "rights declaration contains sensitive material")
        if (
            basis not in ALLOWED_RIGHTS
            or lifecycle in DENIED_LIFECYCLES
            or lifecycle != "provider_eligible"
            or source_class != ALLOWED_SOURCE_BY_RIGHTS.get(basis)
            or file_name.lower() in DENIED_TIKTOK_FILE_NAMES
            or digest in DENIED_TIKTOK_DIGESTS
            or "third_party" in provenance.lower()
            or "research" in provenance.lower()
        ):
            raise EnhancementError(EnhancementErrorCode.RIGHTS_REJECTED, "input rights do not permit Provider processing")
        return {
            "rights_basis": basis,
            "lifecycle": lifecycle,
            "source_class": source_class,
            "fixture_provenance": provenance,
        }

    @staticmethod
    def _profile(raw: object) -> dict[str, object]:
        value = _mapping(raw, "workflow_profile")
        common = {
            "profile_id", "profile_version", "profile_digest", "provider_kind", "supported_operations",
            "operation_limits", "media_limits", "execution_limits", "rate_snapshot",
        }
        provider_kind = value.get("provider_kind")
        provider_mode = value.get("provider_mode")
        if provider_kind == "offline_fake":
            required = common
        elif provider_mode == "ai_app":
            required = common | {"provider_mode", "ai_app_binding"}
        else:
            required = common | {"workflow_binding"}
        if set(value) != required or provider_kind not in {"offline_fake", "runninghub"} or value.get("profile_version") != "1.0.0":
            raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "workflow profile shape is invalid")
        if provider_kind == "offline_fake":
            approved = fake_workflow_profile(str(value.get("profile_id", "")))
            if value != approved:
                raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "workflow profile does not match an approved offline Fake profile")
        elif provider_mode == "ai_app":
            if value != runninghub_ai_app_profile():
                raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "RunningHub AI application profile is not approved")
        else:
            binding = _mapping(value.get("workflow_binding"), "workflow_profile.workflow_binding")
            if set(binding) != {
                "workflow_id", "workflow_json_sha256", "input_node_id", "input_field_name",
                "node_info_list", "output_origins",
            }:
                raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "RunningHub workflow binding is incomplete")
            for field in ("workflow_id", "input_node_id", "input_field_name"):
                _string(binding, field, EnhancementErrorCode.WORKFLOW_PROFILE_INVALID)
            workflow_digest = binding.get("workflow_json_sha256")
            if not isinstance(workflow_digest, str) or _DIGEST.fullmatch(workflow_digest) is None:
                raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "RunningHub workflow digest is invalid")
            if not isinstance(binding.get("node_info_list"), list) or not binding["node_info_list"]:
                raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "RunningHub node bindings are missing")
            if not isinstance(binding.get("output_origins"), list) or not binding["output_origins"]:
                raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "RunningHub output origins are missing")
        supplied = value.get("profile_digest")
        body = {key: item for key, item in value.items() if key != "profile_digest"}
        if not isinstance(supplied, str) or content_digest(body) != supplied:
            raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "workflow profile digest mismatch")
        supported = value.get("supported_operations")
        if not isinstance(supported, list) or not supported or any(item not in {"upscale", "frame_interpolation", "denoise_restore"} for item in supported):
            raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "workflow profile operations are invalid")
        media = _mapping(value.get("media_limits"), "workflow_profile.media_limits")
        execution = _mapping(value.get("execution_limits"), "workflow_profile.execution_limits")
        operation_limits = _mapping(value.get("operation_limits"), "workflow_profile.operation_limits")
        rate = _mapping(value.get("rate_snapshot"), "workflow_profile.rate_snapshot")
        if set(media) != {"max_duration_seconds", "max_width", "max_height", "max_fps"}:
            raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "workflow media limits are invalid")
        if set(execution) != {"max_requests", "max_concurrency", "max_attempts", "max_timeout_seconds", "max_runtime_seconds"}:
            raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "workflow execution limits are invalid")
        if set(operation_limits) != {
            "upscale_factors", "frame_interpolation_factors", "denoise_strength_min", "denoise_strength_max",
        }:
            raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "workflow operation limits are invalid")
        if set(rate) != {
            "snapshot_at", "instance_type", "currency", "rate_per_hour", "public_source", "estimate_only", "not_a_quote",
        }:
            raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "workflow rate snapshot fields are invalid")
        for field in ("max_duration_seconds", "max_width", "max_height", "max_fps"):
            _positive_number(media.get(field), field, EnhancementErrorCode.WORKFLOW_PROFILE_INVALID)
        for field in ("max_requests", "max_concurrency", "max_attempts", "max_timeout_seconds", "max_runtime_seconds"):
            _positive_int(execution.get(field), field, EnhancementErrorCode.WORKFLOW_PROFILE_INVALID)
        if rate.get("currency") != "USD" or rate.get("estimate_only") is not True or rate.get("not_a_quote") is not True:
            raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "rate snapshot must be an estimate-only USD public snapshot")
        _positive_number(rate.get("rate_per_hour"), "rate_per_hour", EnhancementErrorCode.WORKFLOW_PROFILE_INVALID)
        for field in ("snapshot_at", "instance_type", "public_source"):
            _string(rate, field, EnhancementErrorCode.WORKFLOW_PROFILE_INVALID)
        return snapshot(value)

    @staticmethod
    def _operations(raw: object, profile: Mapping[str, object], input_summary: Mapping[str, object]) -> list[dict[str, object]]:
        if not isinstance(raw, list) or not raw:
            raise EnhancementError(EnhancementErrorCode.OPERATION_UNSUPPORTED, "at least one enhancement operation is required")
        supported = set(profile["supported_operations"])
        limits = _mapping(profile["operation_limits"], "workflow_profile.operation_limits")
        normalized: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in raw:
            operation = _mapping(item, "operations[]")
            kind = _string(operation, "type", EnhancementErrorCode.OPERATION_UNSUPPORTED)
            if kind in seen or kind not in supported:
                raise EnhancementError(EnhancementErrorCode.OPERATION_UNSUPPORTED, "operation is duplicated or unsupported")
            seen.add(kind)
            if kind == "upscale":
                if set(operation) != {"type", "factor"} or operation.get("factor") not in limits.get("upscale_factors", []):
                    raise EnhancementError(EnhancementErrorCode.OPERATION_UNSUPPORTED, "upscale factor is unsupported")
                normalized.append({"type": kind, "factor": operation["factor"]})
            elif kind == "frame_interpolation":
                if set(operation) != {"type", "factor"} or operation.get("factor") not in limits.get("frame_interpolation_factors", []):
                    raise EnhancementError(EnhancementErrorCode.OPERATION_UNSUPPORTED, "frame interpolation factor is unsupported")
                normalized.append({"type": kind, "factor": operation["factor"]})
            else:
                strength = operation.get("strength")
                minimum = limits.get("denoise_strength_min")
                maximum = limits.get("denoise_strength_max")
                if set(operation) != {"type", "strength"} or isinstance(strength, bool) or not isinstance(strength, (int, float)) or not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)) or not minimum <= strength <= maximum:
                    raise EnhancementError(EnhancementErrorCode.OPERATION_UNSUPPORTED, "denoise/restore strength is unsupported")
                normalized.append({"type": kind, "strength": strength})
        media = profile["media_limits"]
        output_width = int(input_summary["width"])
        output_height = int(input_summary["height"])
        output_fps = float(input_summary["fps"])
        for operation in normalized:
            if operation["type"] == "upscale":
                output_width *= int(operation["factor"])
                output_height *= int(operation["factor"])
            elif operation["type"] == "frame_interpolation":
                output_fps *= int(operation["factor"])
        if (
            float(input_summary["duration_seconds"]) > float(media["max_duration_seconds"])
            or int(input_summary["width"]) > int(media["max_width"])
            or int(input_summary["height"]) > int(media["max_height"])
            or float(input_summary["fps"]) > float(media["max_fps"])
            or output_width > int(media["max_width"])
            or output_height > int(media["max_height"])
            or output_fps > float(media["max_fps"])
        ):
            raise EnhancementError(EnhancementErrorCode.WORKFLOW_PROFILE_INVALID, "input exceeds the selected workflow profile")
        return normalized

    @staticmethod
    def _budget(raw: object, profile: Mapping[str, object]) -> tuple[dict[str, object], dict[str, object]]:
        value = _mapping(raw, "budget")
        required = {"max_cost_usd", "max_requests", "max_concurrency", "max_attempts", "timeout_seconds"}
        if set(value) != required:
            raise EnhancementError(EnhancementErrorCode.BUDGET_INVALID, "budget fields are invalid")
        maximum = _positive_number(value.get("max_cost_usd"), "max_cost_usd", EnhancementErrorCode.BUDGET_INVALID)
        execution = profile["execution_limits"]
        for field, cap_field in (
            ("max_requests", "max_requests"),
            ("max_concurrency", "max_concurrency"),
            ("max_attempts", "max_attempts"),
            ("timeout_seconds", "max_timeout_seconds"),
        ):
            amount = _positive_int(value.get(field), field, EnhancementErrorCode.BUDGET_INVALID)
            if amount > int(execution[cap_field]):
                raise EnhancementError(EnhancementErrorCode.BUDGET_INVALID, "budget exceeds the workflow profile execution cap")
        rate = profile["rate_snapshot"]
        estimated = float(rate["rate_per_hour"]) * int(execution["max_runtime_seconds"]) / 3600
        if estimated > maximum:
            raise EnhancementError(EnhancementErrorCode.BUDGET_EXCEEDED, "estimated enhancement cost exceeds the approved budget")
        cost = {
            "currency": "USD",
            "instance_type": rate["instance_type"],
            "rate_per_hour": rate["rate_per_hour"],
            "rate_snapshot_at": rate["snapshot_at"],
            "public_source": rate["public_source"],
            "max_runtime_seconds": execution["max_runtime_seconds"],
            "estimated_cost_usd": estimated,
            "estimate_only": True,
            "not_a_quote": True,
        }
        return snapshot(value), cost
