"""Explicitly authorized Apify adapters for Viral Research.

The collection adapter is single-use by design: one ``fetch`` call starts one
Actor run and reads its resulting metadata dataset once. Media download remains
fail-closed until a separate download authorization is issued.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
from typing import Callable, Mapping, Protocol, Sequence
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .errors import ErrorCode, SkillError


APIFY_RESEARCH_AUTHORIZATION_ID = "FTG-P-RESEARCH-001"
APIFY_TIKTOK_ACTOR_ID = "apidojo/tiktok-scraper"
_APIFY_TIKTOK_ACTOR_PATH = "apidojo~tiktok-scraper"
_API_ROOT = "https://api.apify.com/v2"
_MAX_RESULTS = 20
_MAX_TOTAL_CHARGE_USD = 0.01
_RETENTION_DAYS = 7
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}(?!\d)")
_UNSAFE_TERMS = re.compile(r"(?i)\b(?:doxx|doxing|hate crime|self[- ]harm|suicide instructions)\b")


class JsonTransport(Protocol):
    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None,
        timeout_seconds: int,
    ) -> object: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent bearer credentials from following redirects to any destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


class _UrllibJsonTransport:
    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None,
        timeout_seconds: int,
    ) -> object:
        if not url.startswith(f"{_API_ROOT}/"):
            raise ValueError("transport URL is outside the authorized Provider origin")
        request = Request(url, data=body, headers=headers, method=method)
        opener = build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


@dataclass(frozen=True)
class ApifyRunReceipt:
    actor_id: str
    actor_run_id: str
    actor_status: str
    returned_count: int
    actual_cost_usd: float
    charged_event_counts: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "actor_run_id": self.actor_run_id,
            "actor_status": self.actor_status,
            "returned_count": self.returned_count,
            "actual_cost_usd": self.actual_cost_usd,
            "charged_event_counts": dict(self.charged_event_counts),
        }


def resolve_apify_api_key(environ: Mapping[str, str] | None = None) -> str:
    """Resolve the credential from the sole authorized environment variable."""
    source = os.environ if environ is None else environ
    value = source.get("APIFY_API_KEY")
    if not isinstance(value, str) or not value.strip():
        raise SkillError(
            ErrorCode.PROVIDER_FORBIDDEN,
            "The authorized Provider credential is unavailable",
        )
    return value.strip()


def _utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return 0.0
    return max(0.0, float(value))


def _published_at(row: Mapping[str, object]) -> str:
    formatted = row.get("uploadedAtFormatted")
    if isinstance(formatted, str) and formatted.endswith("Z"):
        try:
            datetime.fromisoformat(formatted[:-1] + "+00:00")
        except ValueError:
            pass
        else:
            return formatted
    timestamp = row.get("uploadedAt")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        try:
            return _utc_z(datetime.fromtimestamp(float(timestamp), tz=timezone.utc))
        except (OverflowError, OSError, ValueError):
            pass
    raise SkillError(
        ErrorCode.VALIDATION_FAILED,
        "Provider result is missing a valid publication timestamp",
        field_paths=("published_at",),
    )


def _normalized_post(row: Mapping[str, object], *, retrieved_at: datetime) -> dict[str, object]:
    source_id = row.get("id")
    title = row.get("title")
    source_url = row.get("postPage")
    if not isinstance(source_id, (str, int)) or not str(source_id).strip():
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Provider result is missing a source identity")
    if not isinstance(title, str) or not title.strip():
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Provider result is missing a title")
    if not isinstance(source_url, str) or not source_url.startswith("https://www.tiktok.com/"):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Provider result has an invalid public source URL")
    pii_detected = bool(_EMAIL.search(title) or _PHONE.search(title))
    views = _number(row.get("views"))
    comments = _number(row.get("comments"))
    return {
        "source_id": str(source_id).strip(),
        "source_url": source_url,
        "title": title.strip(),
        "description": title.strip(),
        "published_at": _published_at(row),
        "retrieved_at": _utc_z(retrieved_at),
        "views": views,
        "likes": _number(row.get("likes")),
        "comments": comments,
        "shares": _number(row.get("shares")),
        "comment_quality": min(1.0, comments / max(1.0, views) * 100.0),
        "reproducibility": 0.5,
        "production_feasibility": 0.5,
        "platform_fit": 1.0,
        "brand_safety": 0.0 if _UNSAFE_TERMS.search(title) else 0.5,
        "rights_status": "UNKNOWN",
        "pii_detected": pii_detected,
        "expires_at": _utc_z(retrieved_at + timedelta(days=_RETENTION_DAYS)),
    }


class ApifyCollectionAdapter:
    """Single-run, metadata-only adapter for the authorized TikTok Actor."""

    def __init__(
        self, *, authorization_id: str, seed_queries: Sequence[str], market: str,
        transport: JsonTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if authorization_id != APIFY_RESEARCH_AUTHORIZATION_ID:
            raise SkillError(ErrorCode.PROVIDER_FORBIDDEN, "Provider authorization is invalid")
        normalized_queries = tuple(
            dict.fromkeys(query.strip() for query in seed_queries if isinstance(query, str) and query.strip())
        )
        if len(normalized_queries) not in (2, 3):
            raise SkillError(
                ErrorCode.VALIDATION_FAILED,
                "Authorized smoke requires two or three seed queries",
                field_paths=("seed_queries",),
            )
        if market != "US":
            raise SkillError(
                ErrorCode.PROVIDER_FORBIDDEN,
                "Authorized smoke is restricted to the US market",
                field_paths=("market",),
            )
        self._authorization_id = authorization_id
        self._seed_queries = normalized_queries
        self._market = market
        self._transport = transport or _UrllibJsonTransport()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._receipt: ApifyRunReceipt | None = None
        self.attempt_count = 0

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(authorization_id={self._authorization_id!r}, "
            f"seed_query_count={len(self._seed_queries)}, market={self._market!r}, credential='[REDACTED]')"
        )

    @property
    def is_authorized(self) -> bool:
        return self._authorization_id == APIFY_RESEARCH_AUTHORIZATION_ID

    @property
    def receipt(self) -> ApifyRunReceipt:
        if self._receipt is None:
            raise SkillError(ErrorCode.PROVIDER_FAILURE, "Provider run receipt is not available")
        return self._receipt

    def fetch(self, query: str, *, limit: int, timeout_seconds: int):
        del query
        if self.attempt_count:
            raise SkillError(ErrorCode.BUDGET_EXCEEDED, "Authorized adapter permits only one Actor run")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 10 <= limit <= _MAX_RESULTS:
            raise SkillError(
                ErrorCode.BUDGET_EXCEEDED,
                "Authorized Actor run requires a result limit between 10 and 20",
                field_paths=("search_budget.max_results",),
            )
        credential = resolve_apify_api_key()
        self.attempt_count += 1
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
        }
        query_parameters = urlencode({
            "waitForFinish": min(60, timeout_seconds),
            "maxItems": limit,
            "maxTotalChargeUsd": _MAX_TOTAL_CHARGE_USD,
            "restartOnError": "false",
        })
        run_url = f"{_API_ROOT}/acts/{_APIFY_TIKTOK_ACTOR_PATH}/runs?{query_parameters}"
        actor_input = {
            "keywords": list(self._seed_queries),
            "location": self._market,
            "dateRange": "THIS_MONTH",
            "sortType": "RELEVANCE",
            "includeSearchKeywords": True,
            "maxItems": limit,
        }
        try:
            run_response = self._transport.request(
                "POST", run_url, headers=headers,
                body=json.dumps(actor_input, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                timeout_seconds=timeout_seconds,
            )
            if not isinstance(run_response, Mapping) or not isinstance(run_response.get("data"), Mapping):
                raise ValueError("invalid run response")
            run = run_response["data"]
            status = run.get("status")
            if status != "SUCCEEDED":
                raise ValueError("actor did not reach a successful terminal state")
            run_id = run.get("id")
            dataset_id = run.get("defaultDatasetId")
            cost = run.get("usageTotalUsd")
            if not isinstance(run_id, str) or not isinstance(dataset_id, str):
                raise ValueError("run identifiers missing")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id) or not re.fullmatch(r"[A-Za-z0-9_-]+", dataset_id):
                raise ValueError("run identifiers invalid")
            if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(float(cost)):
                raise ValueError("run cost missing")
            if float(cost) < 0 or float(cost) > _MAX_TOTAL_CHARGE_USD:
                raise ValueError("run cost exceeded the authorized cap")
            dataset_url = (
                f"{_API_ROOT}/datasets/{dataset_id}/items?"
                + urlencode({"clean": "true", "format": "json", "limit": limit})
            )
            dataset = self._transport.request(
                "GET", dataset_url, headers=headers, body=None, timeout_seconds=timeout_seconds,
            )
            if not isinstance(dataset, list) or not all(isinstance(item, Mapping) for item in dataset):
                raise ValueError("invalid dataset response")
            retrieved_at = self._now()
            if retrieved_at.tzinfo is None:
                raise ValueError("adapter clock must be timezone-aware")
            rows = tuple(_normalized_post(item, retrieved_at=retrieved_at) for item in dataset[:limit])
            raw_events = run.get("chargedEventCounts", {})
            events = {
                str(name): int(count) for name, count in raw_events.items()
                if isinstance(raw_events, Mapping) and isinstance(count, int) and not isinstance(count, bool)
            }
            self._receipt = ApifyRunReceipt(
                actor_id=APIFY_TIKTOK_ACTOR_ID,
                actor_run_id=run_id,
                actor_status=status,
                returned_count=len(rows),
                actual_cost_usd=float(cost),
                charged_event_counts=events,
            )
            return rows
        except SkillError:
            raise
        except Exception:
            raise SkillError(
                ErrorCode.PROVIDER_FAILURE,
                "Authorized Apify Actor run failed; no retry was attempted",
                retryable=False,
            ) from None


class ApifyDownloadAdapter:
    """Staged production seam; real media bytes need a separate FTG-P grant."""

    def __init__(self, *, authorization_id: str) -> None:
        self._authorization_id = authorization_id
        self.attempt_count = 0

    def __repr__(self) -> str:
        return f"{type(self).__name__}(authorization_id={self._authorization_id!r}, enabled=False)"

    def download(self, candidate: Mapping[str, object]):
        del candidate
        self.attempt_count += 1
        raise SkillError(
            ErrorCode.DOWNLOAD_FORBIDDEN,
            "The current Provider authorization does not include media download",
        )
