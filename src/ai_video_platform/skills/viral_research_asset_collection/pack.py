"""Canonical ViralResearchPack projection over the owner-local result."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json

from .errors import ErrorCode, SkillError
from .models import ResearchResult, ViralResearchPack


_CONTRACT_IDENTITY = "avp.contract.viral-research-pack"
_CONTRACT_VERSION = "1.0.0"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _counter(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Execution counter must be a non-negative integer", field_paths=(field,))
    return value


def project_viral_research_pack(
    request: Mapping[str, object],
    result: ResearchResult,
    *,
    external_provider_calls: int,
    network_calls: int,
) -> ViralResearchPack:
    """Publish the registered artifact without replacing ResearchResult."""
    external_provider_calls = _counter(external_provider_calls, "external_provider_calls")
    network_calls = _counter(network_calls, "network_calls")
    if result.status != "COMPLETED":
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Only completed research can publish ViralResearchPack")
    request_digest = result.request_digest
    try:
        supplied_request_digest = _digest(dict(request))
    except (TypeError, ValueError) as exc:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "ViralResearchPack request must be JSON-compatible") from exc
    if supplied_request_digest != request_digest:
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "ResearchResult does not belong to the ViralResearchPack request",
            field_paths=("request_digest",),
        )
    ranked_results: list[dict[str, object]] = []
    retrieved_times: list[str] = []
    for rank, candidate in enumerate(result.candidates, start=1):
        candidate_value = candidate.to_dict()
        metadata = candidate_value["source_metadata"]
        comment_evidence = candidate_value["comment_evidence"]
        provenance = candidate_value["source_provenance"]
        if (
            not isinstance(metadata, Mapping)
            or not metadata
            or not isinstance(comment_evidence, Mapping)
            or not comment_evidence
            or not isinstance(provenance, Mapping)
            or not provenance
        ):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Research candidate evidence is incomplete")
        retrieved_at = metadata.get("retrieved_at")
        if isinstance(retrieved_at, str) and retrieved_at != "UNAVAILABLE":
            retrieved_times.append(retrieved_at)
        score = candidate.score.to_dict()
        ranked_results.append({
            "rank": rank,
            "source_id": candidate.source_id,
            "source_url": candidate.source_url,
            "title": candidate.title,
            "content_digest": candidate.content_digest,
            "source_metadata": dict(metadata),
            "comment_evidence": dict(comment_evidence),
            "source_provenance": dict(provenance),
            "score": score,
            "decisions": {
                "rights": {"status": candidate.rights_status},
                "safety": {
                    "pii_detected": candidate.pii_detected,
                    "brand_safety": metadata.get("brand_safety", "UNAVAILABLE"),
                },
                "retention": {"expires_at": candidate.expires_at},
                "lifecycle": {"state": candidate.lifecycle_state, "reasons": list(candidate.reasons)},
            },
        })
    time_window = request.get("time_window")
    search_budget = request.get("search_budget")
    download_policy = request.get("download_policy")
    fallback_time = time_window.get("end") if isinstance(time_window, Mapping) else "UNAVAILABLE"
    produced_at = max(retrieved_times) if retrieved_times else fallback_time
    identity_basis = {
        "contract_identity": _CONTRACT_IDENTITY,
        "contract_version": _CONTRACT_VERSION,
        "request_digest": request_digest,
        "ranked_content": [
            {"source_id": item["source_id"], "content_digest": item["content_digest"]}
            for item in ranked_results
        ],
    }
    artifact: dict[str, object] = {
        "artifact_name": "ViralResearchPack",
        "contract_identity": _CONTRACT_IDENTITY,
        "contract_version": _CONTRACT_VERSION,
        "artifact_id": f"viral-research-pack-{_digest(identity_basis)[:24]}",
        "produced_at": produced_at,
        "producer": {
            "component_id": "viral-research-asset-collection",
            "workline_id": "codex-02",
        },
        "request_provenance": {
            "request_digest": request_digest,
            "idempotency_key": request.get("idempotency_key"),
            "platform": request.get("platform"),
            "market": request.get("market"),
            "region": request.get("region"),
            "campaign_goal": request.get("campaign_goal"),
            "target_audience": request.get("target_audience"),
            "content_format": request.get("content_format"),
            "time_window": dict(time_window) if isinstance(time_window, Mapping) else {},
            "search_budget": dict(search_budget) if isinstance(search_budget, Mapping) else {},
            "download_policy": dict(download_policy) if isinstance(download_policy, Mapping) else {},
            "seed_queries": list(request.get("seed_queries", ())),
        },
        "ranked_results": ranked_results,
        "partial": result.partial,
        "execution_counters": {
            "collection_attempts": result.provider_calls,
            "external_provider_calls": external_provider_calls,
            "network_calls": network_calls,
        },
    }
    artifact["artifact_digest"] = _digest(artifact)
    return ViralResearchPack(artifact=artifact)


__all__ = ["project_viral_research_pack"]
