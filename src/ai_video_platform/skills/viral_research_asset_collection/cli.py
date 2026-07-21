"""Skill-local machine-readable CLI; real seams remain rejecting by default."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Sequence

from .adapters import RejectingCollectionAdapter, RejectingDownloadAdapter
from .apify import ApifyCollectionAdapter
from .errors import ErrorCode, SkillError
from .interface import collect_reference_assets, inspect_research_request, research_viral
from .storage import InMemoryResearchLibraryAdapter, ResearchLibraryAdapter


def _utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not value.endswith("Z"):
        raise ValueError("--now must use UTC Z form")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="viral-research-asset-collection")
    parser.add_argument("command", choices=("inspect-research-request", "research-viral", "collect-reference-assets"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--now")
    parser.add_argument("--provider", choices=("rejecting", "apify"), default="rejecting")
    parser.add_argument("--authorization-id")
    parser.add_argument("--library-root")
    arguments = parser.parse_args(argv)
    try:
        request = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
        now = _utc(arguments.now)
        apify_adapter = None
        if arguments.command == "inspect-research-request":
            result = inspect_research_request(request, now=now)
        elif arguments.command == "research-viral":
            provider = RejectingCollectionAdapter()
            storage = InMemoryResearchLibraryAdapter()
            if arguments.provider == "apify":
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
            result = research_viral(
                request,
                provider=provider,
                storage=storage,
                now=now,
            )
        else:
            result = collect_reference_assets(
                request,
                downloader=RejectingDownloadAdapter(),
                storage=InMemoryResearchLibraryAdapter(),
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
