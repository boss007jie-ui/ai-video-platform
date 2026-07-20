"""Small public interface over the deep offline Viral Research module."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Protocol

from .errors import ErrorCode, SkillError
from .models import CollectionItem, CollectionResult, ResearchCandidate, ResearchInspection, ResearchResult, ResearchScore


class CollectionProvider(Protocol):
    def fetch(self, query: str, *, limit: int, timeout_seconds: int) -> Sequence[Mapping[str, object]]: ...


class ResearchStorage(Protocol):
    def write_record(self, record: Mapping[str, object], *, idempotency_key: str) -> None: ...


class DownloadAdapter(Protocol):
    def download(self, candidate: Mapping[str, object]) -> Mapping[str, object]: ...


_BUDGET_LIMITS = {"max_queries": 50, "max_results": 500, "max_provider_calls": 10, "timeout_seconds": 60}
_POLICY_GUARDS = (
    "public_or_authorized_only", "no_drm_bypass", "no_login_bypass",
    "no_private_content", "no_unauthorized_reposting",
)
_TOKEN = re.compile(r"[a-z0-9]+")
_SCORE_FACTORS = (
    "relevance", "freshness", "engagement_velocity", "comment_quality",
    "reproducibility", "production_feasibility", "platform_fit", "brand_safety",
    "rights_status", "duplicate_distance",
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _parse_z(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Timestamp must use UTC Z form", field_paths=(field,))
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Timestamp is invalid", field_paths=(field,)) from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Timestamp must use UTC", field_paths=(field,))
    return parsed


def _required_text(request: Mapping[str, object], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Required field is missing", field_paths=(field,))
    return value.strip()


def _validated_budget(request: Mapping[str, object]) -> dict[str, int]:
    value = request.get("search_budget")
    if not isinstance(value, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "search_budget must be an object", field_paths=("search_budget",))
    budget: dict[str, int] = {}
    for name, ceiling in _BUDGET_LIMITS.items():
        item = value.get(name)
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Budget values must be positive integers", field_paths=(f"search_budget.{name}",))
        if item > ceiling:
            raise SkillError(ErrorCode.BUDGET_EXCEEDED, "Search budget exceeds the offline hard ceiling", field_paths=(f"search_budget.{name}",))
        budget[name] = item
    return budget


def inspect_research_request(
    request: Mapping[str, object], *, now: datetime | None = None,
) -> ResearchInspection:
    if not isinstance(request, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Request must be an object")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "now must be timezone-aware", field_paths=("now",))
    for field in ("platform", "market", "region", "campaign_goal", "target_audience", "content_format", "idempotency_key"):
        _required_text(request, field)
    window = request.get("time_window")
    if not isinstance(window, Mapping):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "time_window must be an object", field_paths=("time_window",))
    start = _parse_z(window.get("start"), "time_window.start")
    end = _parse_z(window.get("end"), "time_window.end")
    expires = _parse_z(window.get("expires_at"), "time_window.expires_at")
    if start >= end or end >= expires:
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "time_window must satisfy start < end < expires_at",
            field_paths=("time_window.start", "time_window.end", "time_window.expires_at"),
        )
    if expires <= current:
        raise SkillError(ErrorCode.REQUEST_EXPIRED, "Research request has expired", field_paths=("time_window.expires_at",))
    budget = _validated_budget(request)
    policy = request.get("download_policy")
    if not isinstance(policy, Mapping) or policy.get("mode") not in {"METADATA_ONLY", "FREE_FIRST"}:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "download_policy mode is unsupported", field_paths=("download_policy.mode",))
    unsafe = tuple(name for name in _POLICY_GUARDS if policy.get(name) is not True)
    if unsafe:
        raise SkillError(ErrorCode.RIGHTS_FORBIDDEN, "All public/authorized and no-bypass guards are mandatory", field_paths=tuple(f"download_policy.{name}" for name in unsafe))
    seeds = request.get("seed_queries")
    if not isinstance(seeds, Sequence) or isinstance(seeds, (str, bytes)):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "seed_queries must be an array", field_paths=("seed_queries",))
    normalized_seeds = tuple(dict.fromkeys(str(seed).strip() for seed in seeds if isinstance(seed, str) and seed.strip()))
    if not normalized_seeds:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "At least one seed query is required", field_paths=("seed_queries",))
    campaign_goal = str(request["campaign_goal"]).strip()
    audience = str(request["target_audience"]).strip()
    content_format = str(request["content_format"]).strip()
    variants: list[str] = list(normalized_seeds)
    for seed in normalized_seeds:
        variants.extend((f"{seed} {campaign_goal}", f"{seed} {audience}", f"{seed} {content_format}"))
    expanded = tuple(dict.fromkeys(variants))[:budget["max_queries"]]
    return ResearchInspection(status="READY", request_digest=_digest(dict(request)), expanded_queries=expanded)


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(value.lower()))


def _similarity(left: Mapping[str, object], right: Mapping[str, object]) -> float:
    left_tokens = _tokens(f"{left.get('title', '')} {left.get('description', '')}")
    right_tokens = _tokens(f"{right.get('title', '')} {right.get('description', '')}")
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _number(row: Mapping[str, object], name: str, default: float = 0.0) -> float:
    value = row.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return default
    return max(0.0, float(value))


def _normalized_candidate(row: Mapping[str, object]) -> dict[str, object]:
    required = ("source_id", "source_url", "title", "published_at", "rights_status", "expires_at")
    missing = tuple(name for name in required if not isinstance(row.get(name), str) or not str(row.get(name)).strip())
    if missing:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Provider result is missing normalized fields", field_paths=missing)
    safe_names = (
        "source_id", "source_url", "title", "description", "published_at", "retrieved_at",
        "views", "likes", "comments", "shares", "comment_quality", "reproducibility",
        "production_feasibility", "platform_fit", "brand_safety", "rights_status",
        "pii_detected", "expires_at",
    )
    return {name: row.get(name) for name in safe_names}


def _score(row: Mapping[str, object], queries: Sequence[str], now: datetime) -> ResearchScore:
    content_tokens = _tokens(f"{row.get('title', '')} {row.get('description', '')}")
    query_tokens = set().union(*(_tokens(query) for query in queries)) if queries else set()
    relevance = len(content_tokens & query_tokens) / max(1, len(query_tokens))
    age_days = max(0.0, (now - _parse_z(row["published_at"], "published_at")).total_seconds() / 86400)
    views = max(1.0, _number(row, "views", 1.0))
    inputs = {
        "relevance": min(1.0, relevance),
        "freshness": max(0.0, 1.0 - age_days / 30.0),
        "engagement_velocity": min(1.0, (_number(row, "likes") + _number(row, "comments") + _number(row, "shares")) / views),
        "comment_quality": min(1.0, _number(row, "comment_quality")),
        "reproducibility": min(1.0, _number(row, "reproducibility")),
        "production_feasibility": min(1.0, _number(row, "production_feasibility")),
        "platform_fit": min(1.0, _number(row, "platform_fit")),
        "brand_safety": min(1.0, _number(row, "brand_safety")),
        "rights_status": 1.0 if row.get("rights_status") in {"PUBLIC", "AUTHORIZED"} else 0.0,
        "duplicate_distance": float(row.get("_duplicate_distance", 1.0)),
    }
    weights = {name: 1.0 / len(_SCORE_FACTORS) for name in _SCORE_FACTORS}
    contributions = {name: round(inputs[name] * weights[name], 8) for name in _SCORE_FACTORS}
    return ResearchScore(
        total=sum(contributions.values()),
        inputs=inputs,
        weights=weights,
        contributions=contributions,
        explanation=contributions,
    )


def _lifecycle(row: Mapping[str, object], now: datetime) -> tuple[str, tuple[str, ...]]:
    if _parse_z(row["expires_at"], "expires_at") <= now:
        return "expired", ("expiry_reached",)
    brand_safety = row.get("brand_safety")
    if row.get("pii_detected") is True or not isinstance(brand_safety, (int, float)) or isinstance(brand_safety, bool) or not 0 <= float(brand_safety) <= 1 or float(brand_safety) < 0.5:
        return "quarantined", ("pii_or_brand_safety",)
    if row.get("rights_status") not in {"PUBLIC", "AUTHORIZED"}:
        return "metadata_only", ("rights_unconfirmed",)
    return "retained", ()


def research_viral(
    request: Mapping[str, object], *, provider: CollectionProvider, storage: ResearchStorage,
    now: datetime | None = None, cancelled: Callable[[], bool] | None = None,
) -> ResearchResult:
    current = now or datetime.now(timezone.utc)
    inspection = inspect_research_request(request, now=current)
    if cancelled and cancelled():
        raise SkillError(ErrorCode.CANCELLED, "Research was cancelled")
    budget = _validated_budget(request)
    retry_limit = request.get("retry_limit", 0)
    if not isinstance(retry_limit, int) or isinstance(retry_limit, bool) or retry_limit < 0:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "retry_limit must be a non-negative integer", field_paths=("retry_limit",))
    retry_limit = min(retry_limit, 2)
    provider_calls = 0
    rows: list[dict[str, object]] = []
    for query in inspection.expanded_queries:
        if provider_calls >= budget["max_provider_calls"] or len(rows) >= budget["max_results"]:
            break
        attempts_for_query = 0
        while provider_calls < budget["max_provider_calls"]:
            if cancelled and cancelled():
                raise SkillError(ErrorCode.CANCELLED, "Research was cancelled")
            provider_calls += 1
            try:
                try:
                    fetched = provider.fetch(query, limit=budget["max_results"] - len(rows), timeout_seconds=budget["timeout_seconds"])
                except SkillError:
                    raise
                except Exception as exc:
                    raise SkillError(ErrorCode.PROVIDER_FAILURE, "Collection Provider failed", retryable=False) from exc
                rows.extend(_normalized_candidate(row) for row in fetched)
                break
            except SkillError as exc:
                if not exc.retryable or attempts_for_query >= retry_limit or provider_calls >= budget["max_provider_calls"]:
                    raise
                attempts_for_query += 1
    unique: list[dict[str, object]] = []
    seen_source_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_digests: set[str] = set()
    for row in rows:
        source_id = str(row["source_id"]).strip().casefold()
        source_url = str(row["source_url"]).strip().casefold().rstrip("/")
        content_digest = _digest({"title": row.get("title"), "description": row.get("description")})
        similarities = [_similarity(row, previous) for previous in unique]
        nearest_similarity = max(similarities, default=0.0)
        if source_id in seen_source_ids or source_url in seen_urls or content_digest in seen_digests or nearest_similarity >= 0.8:
            continue
        seen_source_ids.add(source_id)
        seen_urls.add(source_url)
        seen_digests.add(content_digest)
        row["_content_digest"] = content_digest
        row["_duplicate_distance"] = round(1.0 - nearest_similarity, 6)
        unique.append(row)
        if len(unique) >= budget["max_results"]:
            break
    candidates: list[ResearchCandidate] = []
    for row in unique:
        state, reasons = _lifecycle(row, current)
        content_digest = str(row["_content_digest"])
        candidate = ResearchCandidate(
            source_id=str(row["source_id"]), source_url=str(row["source_url"]), title=str(row["title"]),
            content_digest=content_digest, lifecycle_state=state, rights_status=str(row["rights_status"]),
            pii_detected=row.get("pii_detected") is True, expires_at=str(row["expires_at"]),
            score=_score(row, inspection.expanded_queries, current), reasons=reasons,
        )
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item.score.total, item.source_id))
    for candidate in candidates:
        try:
            storage.write_record(
                {**candidate.to_dict(), "retention_until": candidate.expires_at},
                idempotency_key=f"{request['idempotency_key']}:{candidate.source_id}",
            )
        except SkillError:
            raise
        except Exception as exc:
            raise SkillError(ErrorCode.STORAGE_CONFLICT, "Research storage failed") from exc
    return ResearchResult(
        status="COMPLETED", request_digest=inspection.request_digest,
        provider_calls=provider_calls, candidates=tuple(candidates),
        partial=provider_calls >= budget["max_provider_calls"] and len(inspection.expanded_queries) > provider_calls,
    )


def collect_reference_assets(
    request: Mapping[str, object], *, downloader: DownloadAdapter, storage: ResearchStorage,
    now: datetime | None = None, cancelled: Callable[[], bool] | None = None,
) -> CollectionResult:
    current = now or datetime.now(timezone.utc)
    selected = request.get("selected_candidates")
    policy = request.get("download_policy")
    idempotency_key = request.get("idempotency_key")
    if not isinstance(selected, Sequence) or isinstance(selected, (str, bytes)) or not selected:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "selected_candidates must be a non-empty array")
    if policy not in {"METADATA_ONLY", "FREE_FIRST"} or not isinstance(idempotency_key, str) or not idempotency_key:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Collection policy or idempotency key is invalid")
    normalized: list[dict[str, object]] = []
    for raw in selected:
        if not isinstance(raw, Mapping):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Selected candidate must be an object")
        source_id = _required_text(raw, "source_id")
        source_url = _required_text(raw, "source_url")
        rights = _required_text(raw, "rights_status")
        expires_at = _required_text(raw, "expires_at")
        brand_safety = raw.get("brand_safety")
        if not isinstance(brand_safety, (int, float)) or isinstance(brand_safety, bool) or not 0 <= float(brand_safety) <= 1:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "brand_safety must be between zero and one", field_paths=("brand_safety",))
        expired = _parse_z(expires_at, "expires_at") <= current
        if policy == "FREE_FIRST" and not expired and raw.get("pii_detected") is not True and float(brand_safety) >= 0.5 and rights not in {"PUBLIC", "AUTHORIZED"}:
            raise SkillError(ErrorCode.RIGHTS_FORBIDDEN, "FREE_FIRST requires public or authorized rights")
        normalized.append({
            "raw": raw, "source_id": source_id, "source_url": source_url, "rights": rights,
            "expires_at": expires_at, "expired": expired, "brand_safety": float(brand_safety),
        })

    items: list[CollectionItem] = []
    for selected_item in normalized:
        if cancelled and cancelled():
            raise SkillError(ErrorCode.CANCELLED, "Collection was cancelled")
        raw = selected_item["raw"]
        source_id = str(selected_item["source_id"])
        source_url = str(selected_item["source_url"])
        rights = str(selected_item["rights"])
        expires_at = str(selected_item["expires_at"])
        expired = bool(selected_item["expired"])
        if expired:
            state, object_digest = "expired", None
        elif raw.get("pii_detected") is True or float(selected_item["brand_safety"]) < 0.5:
            state, object_digest = "quarantined", None
        elif policy == "METADATA_ONLY":
            state, object_digest = "metadata_only", None
        else:
            try:
                receipt = downloader.download(raw)
            except SkillError:
                raise
            except Exception as exc:
                raise SkillError(ErrorCode.DOWNLOAD_FORBIDDEN, "Download adapter failed") from exc
            digest = receipt.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise SkillError(ErrorCode.VALIDATION_FAILED, "Download receipt digest is invalid")
            state, object_digest = "collected", digest
        item = CollectionItem(source_id=source_id, lifecycle_state=state, rights_status=rights, object_digest=object_digest)
        try:
            storage.write_record(
                {
                    "source_id": source_id, "source_url": source_url, "lifecycle_state": state,
                    "rights_status": rights, "pii_detected": raw.get("pii_detected") is True,
                    "expires_at": expires_at, "retention_until": expires_at,
                    "object_digest": object_digest,
                },
                idempotency_key=f"{idempotency_key}:{source_id}",
            )
        except SkillError:
            raise
        except Exception as exc:
            raise SkillError(ErrorCode.STORAGE_CONFLICT, "Research storage failed") from exc
        items.append(item)
    return CollectionResult(status="COMPLETED", items=tuple(items))
