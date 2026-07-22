"""Skill-local machine-readable CLI; real seams remain rejecting by default."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Sequence

from .adapters import RejectingCollectionAdapter, RejectingDownloadAdapter
from .errors import SkillError
from .interface import collect_reference_assets, inspect_research_request, research_viral
from .storage import InMemoryResearchLibraryAdapter


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
    arguments = parser.parse_args(argv)
    try:
        request = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
        now = _utc(arguments.now)
        if arguments.command == "inspect-research-request":
            result = inspect_research_request(request, now=now)
        elif arguments.command == "research-viral":
            result = research_viral(
                request,
                provider=RejectingCollectionAdapter(),
                storage=InMemoryResearchLibraryAdapter(),
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
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0
