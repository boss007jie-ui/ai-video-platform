"""Versioned public interfaces for selected-reference analysis and comparison."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import Path
import re

from .analysis import ALGORITHM_VERSION, compare_metrics, summarize_segments, validate_metrics
from .errors import ErrorCode, SkillError
from .models import AnalysisResult, ComparisonResult
from .storage import SafeArtifactWriter


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SCOPE = {"query", "queries", "search_budget", "provider", "download", "discovery", "product_library", "research_library"}
_FORBIDDEN_TOKENS = ("query", "search", "provider", "download", "discovery", "library", "legacy")
_ANALYZE_KEYS = {"analysis_version", "selected_reference"}
_COMPARE_KEYS = {"analysis_version", "analysis", "produced_result"}
_REFERENCE_KEYS = {"reference_id", "source_uri", "sha256", "usage", "provenance", "segments"}
_ANALYSIS_KEYS = {
    "schema_version", "algorithm_version", "analysis_id", "reference_id", "source_uri",
    "source_sha256", "source_provenance", "input_digest", "metrics", "artifact_digest",
}


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required field is missing", field_paths=(field,))
    return value.strip()


def _forbidden_paths(value: object, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).lower()
            path = f"{prefix}.{key}" if prefix else str(key)
            if key_text in _FORBIDDEN_SCOPE or any(token in key_text for token in _FORBIDDEN_TOKENS):
                findings.append(path)
            findings.extend(_forbidden_paths(nested, path))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            findings.extend(_forbidden_paths(nested, f"{prefix}[{index}]"))
    return findings


def _validate_scope(request: Mapping[str, object]) -> None:
    forbidden = sorted(set(_forbidden_paths(request)))
    if forbidden:
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Reference Analysis cannot discover, download, call Providers, or access Libraries", field_paths=tuple(forbidden))


def _strict_keys(mapping: Mapping[str, object], allowed: set[str], field: str) -> None:
    unexpected = sorted(set(mapping) - allowed)
    missing = sorted(allowed - set(mapping))
    if unexpected or missing:
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "Object fields do not match the versioned schema",
            field_paths=tuple([*(f"{field}.{name}" for name in missing), *(f"{field}.{name}" for name in unexpected)]),
        )


def _validate_version(request: Mapping[str, object]) -> None:
    if request.get("analysis_version") != ALGORITHM_VERSION:
        raise SkillError(ErrorCode.VERSION_UNSUPPORTED, "Only analysis version 1.0.0 is supported", field_paths=("analysis_version",))


def _selected_reference(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "selected_reference must be an object", field_paths=("selected_reference",))
    _strict_keys(value, _REFERENCE_KEYS, "selected_reference")
    reference_id = _text(value, "reference_id")
    source_uri = _text(value, "source_uri")
    if source_uri.lower().startswith("file:") or Path(source_uri).is_absolute():
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Reference Analysis does not read local or Library paths", field_paths=("source_uri",))
    sha256 = _text(value, "sha256")
    usage = _text(value, "usage")
    if not _SHA256.fullmatch(sha256):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Selected reference SHA-256 is invalid", field_paths=("sha256",))
    provenance = value.get("provenance")
    if not isinstance(provenance, Mapping) or not provenance:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Selected reference provenance is required", field_paths=("provenance",))
    metrics = summarize_segments(value.get("segments"))
    return {
        "reference_id": reference_id,
        "source_uri": source_uri,
        "sha256": sha256,
        "usage": usage,
        "provenance": dict(provenance),
        "segments": value.get("segments"),
        "metrics": metrics,
    }


def _validated_analysis(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "analysis must be an object", field_paths=("analysis",))
    _strict_keys(value, _ANALYSIS_KEYS, "analysis")
    if value.get("schema_version") != ALGORITHM_VERSION or value.get("algorithm_version") != ALGORITHM_VERSION:
        raise SkillError(ErrorCode.VERSION_UNSUPPORTED, "Analysis artifact version is unsupported")
    input_digest = _text(value, "input_digest")
    artifact_digest = _text(value, "artifact_digest")
    source_sha = _text(value, "source_sha256")
    reference_id = _text(value, "reference_id")
    if not _SHA256.fullmatch(input_digest) or not _SHA256.fullmatch(artifact_digest) or not _SHA256.fullmatch(source_sha):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Analysis digest is invalid")
    if value.get("analysis_id") != f"analysis-{input_digest[:20]}":
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Analysis identity does not match its input digest")
    core = {key: _jsonable(nested) for key, nested in value.items() if key != "artifact_digest"}
    if _digest(core) != artifact_digest:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Analysis artifact digest does not match its content")
    validate_metrics(value.get("metrics"))
    if not reference_id:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Analysis reference identity is missing")
    return value


def analyze_reference(
    request: Mapping[str, object], *, workspace: Path, output_path: str,
    cancelled: Callable[[], bool] | None = None,
) -> AnalysisResult:
    if not isinstance(request, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Request must be an object")
    _validate_scope(request)
    _validate_version(request)
    _strict_keys(request, _ANALYZE_KEYS, "request")
    if cancelled and cancelled():
        raise SkillError(ErrorCode.CANCELLED, "Reference analysis was cancelled")
    selected = _selected_reference(request.get("selected_reference"))
    input_digest = _digest(dict(request))
    artifact: dict[str, object] = {
        "schema_version": ALGORITHM_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "analysis_id": f"analysis-{input_digest[:20]}",
        "reference_id": selected["reference_id"],
        "source_uri": selected["source_uri"],
        "source_sha256": selected["sha256"],
        "source_provenance": selected["provenance"],
        "input_digest": input_digest,
        "metrics": selected["metrics"],
    }
    artifact["artifact_digest"] = _digest(artifact)
    written_path = SafeArtifactWriter(workspace).write(artifact, output_path=output_path, cancelled=cancelled)
    return AnalysisResult(status="COMPLETED", output_path=written_path, artifact=artifact)


def compare_result(
    request: Mapping[str, object], *, workspace: Path, output_path: str,
    cancelled: Callable[[], bool] | None = None,
) -> ComparisonResult:
    if not isinstance(request, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Request must be an object")
    _validate_scope(request)
    _validate_version(request)
    _strict_keys(request, _COMPARE_KEYS, "request")
    if cancelled and cancelled():
        raise SkillError(ErrorCode.CANCELLED, "Reference comparison was cancelled")
    analysis = _validated_analysis(request.get("analysis"))
    reference_id = _text(analysis, "reference_id")
    produced = _selected_reference(request.get("produced_result"))
    if produced["reference_id"] != reference_id:
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Produced result does not match the selected reference", field_paths=("produced_result.reference_id",))
    if produced["sha256"] != analysis["source_sha256"]:
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Produced result source digest does not match the selected reference", field_paths=("produced_result.sha256",))
    differences = compare_metrics(analysis.get("metrics", {}), produced["metrics"])
    input_digest = _digest(dict(request))
    artifact: dict[str, object] = {
        "schema_version": ALGORITHM_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "comparison_id": f"comparison-{input_digest[:20]}",
        "reference_id": reference_id,
        "analysis_id": analysis.get("analysis_id"),
        "input_digest": input_digest,
        **differences,
    }
    written_path = SafeArtifactWriter(workspace).write(artifact, output_path=output_path, cancelled=cancelled)
    return ComparisonResult(status="COMPLETED", output_path=written_path, artifact=artifact)
