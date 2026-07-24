"""Skill-local machine-readable CLI; real seams remain rejecting by default."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Sequence

from .adapters import FakeCollectionAdapter, RejectingCollectionAdapter, RejectingDownloadAdapter
from .apify import ApifyCollectionAdapter
from .errors import ErrorCode, SkillError
from .interface import collect_reference_assets, inspect_research_request, research_viral
from .media import DirectMediaDownloadAdapter
from .pack import project_viral_research_pack
from .storage import InMemoryResearchLibraryAdapter, ResearchLibraryAdapter


def _ensure_utf8_stdout() -> None:
    """Keep machine-readable JSON printable on Windows with non-ASCII metadata."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="strict")


def _utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not value.endswith("Z"):
        raise ValueError("--now must use UTC Z form")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _fake_provider_rows(path: str | None, request: object) -> tuple[dict[str, object], ...]:
    if not path:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Fake Provider requires --provider-fixture")
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(fixture, dict):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Fake Provider fixture must be an object")
    if (
        fixture.get("fixture_version") != "1.0.0"
        or fixture.get("fixture_kind") != "VERSIONED_SYNTHETIC_PROVIDER_RESULTS"
        or fixture.get("request") != request
    ):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Fake Provider fixture identity or request binding is invalid")
    rows = fixture.get("provider_rows")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Fake Provider fixture rows are invalid")
    return tuple(dict(row) for row in rows)


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(prog="viral-research-asset-collection")
    parser.add_argument("command", choices=("inspect-research-request", "research-viral", "collect-reference-assets"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--now")
    parser.add_argument("--provider", choices=("rejecting", "fake", "apify"), default="rejecting")
    parser.add_argument("--provider-fixture")
    parser.add_argument("--authorization-id")
    parser.add_argument("--library-root")
    arguments = parser.parse_args(argv)
    apify_adapter = None
    media_adapter = None
    viral_research_pack = None
    try:
        request = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
        now = _utc(arguments.now)
        if arguments.command == "inspect-research-request":
            result = inspect_research_request(request, now=now)
        elif arguments.command == "research-viral":
            provider = RejectingCollectionAdapter()
            storage = InMemoryResearchLibraryAdapter()
            external_provider_calls = 0
            network_calls = 0
            if arguments.provider == "fake":
                if arguments.authorization_id or arguments.library_root:
                    raise SkillError(ErrorCode.PROVIDER_FORBIDDEN, "Fake Provider does not accept authorization or library flags")
                provider = FakeCollectionAdapter(_fake_provider_rows(arguments.provider_fixture, request))
            elif arguments.provider == "apify":
                if arguments.provider_fixture:
                    raise SkillError(ErrorCode.VALIDATION_FAILED, "Apify does not accept a fake Provider fixture")
                inspection = inspect_research_request(request, now=now)
                del inspection
                if not isinstance(request, dict):
                    raise SkillError(ErrorCode.VALIDATION_FAILED, "Request must be an object")
                budget = request.get("search_budget")
                seeds = request.get("seed_queries")
                policy = request.get("download_policy")
                if (
                    request.get("platform") != "tiktok"
                    or request.get("market") != "US"
                    or not isinstance(seeds, list)
                    or len(tuple(dict.fromkeys(seed.strip() for seed in seeds if isinstance(seed, str) and seed.strip()))) not in (2, 3)
                    or not isinstance(budget, dict)
                    or budget.get("max_provider_calls") != 1
                    or not isinstance(budget.get("max_results"), int)
                    or not 10 <= budget["max_results"] <= 20
                    or request.get("retry_limit", 0) != 0
                    or not isinstance(policy, dict)
                    or policy.get("mode") != "METADATA_ONLY"
                ):
                    raise SkillError(
                        ErrorCode.PROVIDER_FORBIDDEN,
                        "Apify smoke must use TikTok US metadata-only, two or three seeds, one Provider call, 10-20 results, and zero retries",
                    )
                if not arguments.library_root:
                    raise SkillError(ErrorCode.PATH_FORBIDDEN, "Apify smoke requires an explicit Research Library root")
                apify_adapter = ApifyCollectionAdapter(
                    authorization_id=arguments.authorization_id or "",
                    seed_queries=seeds,
                    market="US",
                    now=(lambda: now) if now is not None else None,
                )
                provider = apify_adapter
                storage = ResearchLibraryAdapter(Path(arguments.library_root))
            elif arguments.provider_fixture:
                raise SkillError(ErrorCode.VALIDATION_FAILED, "Rejecting Provider does not accept a fake Provider fixture")
            result = research_viral(
                request,
                provider=provider,
                storage=storage,
                now=now,
            )
            if apify_adapter is not None:
                external_provider_calls = apify_adapter.attempt_count
                network_calls = 2 * apify_adapter.attempt_count
            viral_research_pack = project_viral_research_pack(
                request,
                result,
                external_provider_calls=external_provider_calls,
                network_calls=network_calls,
            )
        else:
            downloader = RejectingDownloadAdapter()
            storage = InMemoryResearchLibraryAdapter()
            if arguments.authorization_id:
                if not arguments.library_root:
                    raise SkillError(ErrorCode.PATH_FORBIDDEN, "Media download requires an explicit Research Library root")
                media_adapter = DirectMediaDownloadAdapter(
                    Path(arguments.library_root), authorization_id=arguments.authorization_id,
                    now=(lambda: now) if now is not None else None,
                )
                downloader = media_adapter
                storage = ResearchLibraryAdapter(Path(arguments.library_root))
            result = collect_reference_assets(
                request,
                downloader=downloader,
                storage=storage,
                now=now,
            )
    except (SkillError, ValueError, OSError, json.JSONDecodeError) as exc:
        error = exc.to_dict() if isinstance(exc, SkillError) else {
            "code": "VIRAL_RESEARCH_INPUT_FAILED", "message": "Input could not be read or parsed", "retryable": False,
            "field_paths": [], "details": {},
        }
        print(json.dumps({"status": "ERROR", "error": error}, ensure_ascii=False, sort_keys=True))
        return 2
    payload = result.to_dict()
    if viral_research_pack is not None:
        payload["viral_research_pack"] = viral_research_pack.to_dict()
    if media_adapter is not None:
        payload["download_receipts"] = list(media_adapter.receipts)
        payload["provider_calls"] = 0
        payload["download_attempts"] = media_adapter.attempt_count
    if apify_adapter is not None:
        if apify_adapter.attempt_count:
            payload["provider_receipt"] = apify_adapter.receipt.to_dict()
        else:
            payload["provider_receipt"] = {
                "status": "IDEMPOTENT_REPLAY",
                "provider_call_performed": False,
            }
        payload["deduped_count"] = len(result.candidates)
        payload["ranking_score_decomposition"] = [
            {"source_id": candidate.source_id, **candidate.score.to_dict()}
            for candidate in result.candidates
        ]
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0
