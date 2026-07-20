"""Versioned public interfaces for selected-reference analysis and comparison."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import Path
import re

from .analysis import ALGORITHM_VERSION, compare_metrics, summarize_segments
from .errors import ErrorCode, SkillError
from .models import AnalysisResult, ComparisonResult
from .storage import SafeArtifactWriter


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SCOPE = {"query", "queries", "search_budget", "provider", "download", "discovery", "product_library", "research_library"}


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


def _validate_scope(request: Mapping[str, object]) -> None:
    forbidden = sorted(_FORBIDDEN_SCOPE & {str(key).lower() for key in request})
    if forbidden:
        raise SkillError(ErrorCode.SCOPE_FORBIDDEN, "Reference Analysis cannot discover, download, call Providers, or access Libraries", field_paths=tuple(forbidden))


def _validate_version(request: Mapping[str, object]) -> None:
    if request.get("analysis_version") != ALGORITHM_VERSION:
        raise SkillError(ErrorCode.VERSION_UNSUPPORTED, "Only analysis version 1.0.0 is supported", field_paths=("analysis_version",))


def _selected_reference(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "selected_reference must be an object", field_paths=("selected_reference",))
    reference_id = _text(value, "reference_id")
    source_uri = _text(value, "source_uri")
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


def analyze_reference(
    request: Mapping[str, object], *, workspace: Path, output_path: str,
    cancelled: Callable[[], bool] | None = None,
) -> AnalysisResult:
    if not isinstance(request, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Request must be an object")
    _validate_scope(request)
    _validate_version(request)
    selected = _selected_reference(request.get("selected_reference"))
    if cancelled and cancelled():
        raise SkillError(ErrorCode.CANCELLED, "Reference analysis was cancelled")
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
    analysis = request.get("analysis")
    if not isinstance(analysis, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "analysis must be an object", field_paths=("analysis",))
    if analysis.get("schema_version") != ALGORITHM_VERSION or analysis.get("algorithm_version") != ALGORITHM_VERSION:
        raise SkillError(ErrorCode.VERSION_UNSUPPORTED, "Analysis artifact version is unsupported")
    reference_id = _text(analysis, "reference_id")
    produced = _selected_reference(request.get("produced_result"))
    if produced["reference_id"] != reference_id:
        raise SkillError(ErrorCode.REFERENCE_MISMATCH, "Produced result does not match the selected reference", field_paths=("produced_result.reference_id",))
    if cancelled and cancelled():
        raise SkillError(ErrorCode.CANCELLED, "Reference comparison was cancelled")
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
