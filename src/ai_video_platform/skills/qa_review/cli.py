"""Independent QA / Review CLI with an allowlisted, atomic output surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from ai_video_platform.contracts.errors import ContractError
from ai_video_platform.contracts.serialization import canonical_json, parse_json_object
from ai_video_platform.core.guards import LegacyPathGuard

from .engine import SKILL_VERSION, review
from .errors import QAError, QAErrorCode
from .models import ReviewArtifacts, ReviewOutcome, ReviewRequest


class QAOutputWriter:
    ALLOWED_FILENAMES = frozenset(
        {
            "feedback-events.json",
            "human-review-package.json",
            "result.json",
            "review-decision.json",
            "skill-execution-event.json",
        }
    )
    _FORBIDDEN_DIRECTORY_NAMES = {
        "ai video product library",
        "ai video research library",
    }

    def __init__(self, output_dir: Path | str) -> None:
        candidate = Path(output_dir).resolve(strict=False)
        normalized_parts = {part.casefold() for part in candidate.parts}
        if normalized_parts.intersection(self._FORBIDDEN_DIRECTORY_NAMES):
            raise QAError(
                QAErrorCode.QA_OUTPUT_PATH_FORBIDDEN,
                "authorization",
                "QA output cannot target a governed Product or Research Library",
                field_paths=("output_dir",),
            )
        LegacyPathGuard().assert_allowed(candidate)
        self.output_dir = candidate

    def _write_json(self, filename: str, value: object) -> None:
        if filename not in self.ALLOWED_FILENAMES:
            raise QAError(
                QAErrorCode.QA_OUTPUT_PATH_FORBIDDEN,
                "authorization",
                "QA output filename is not allowlisted",
                field_paths=("filename",),
            )
        target = self.output_dir / filename
        temporary = self.output_dir / f".{filename}.tmp"
        temporary.write_text(canonical_json(value) + "\n", encoding="utf-8")
        temporary.replace(target)

    def write(self, artifacts: ReviewArtifacts) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "interface_version": "1.0.0",
            "skill_version": SKILL_VERSION,
            "outcome": artifacts.outcome.value,
            "review_decision_ref": artifacts.review_decision["review_decision_id"],
        }
        outputs = {
            "review-decision.json": artifacts.review_decision,
            "feedback-events.json": artifacts.feedback_events,
            "human-review-package.json": artifacts.human_review_package,
            "skill-execution-event.json": artifacts.skill_execution_event,
            "result.json": result,
        }
        for filename in sorted(outputs):
            self._write_json(filename, outputs[filename])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qa-review")
    parser.add_argument(
        "command",
        choices=("review-asset", "review-storyboard", "review-video-plan", "review-video-result"),
    )
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def _error_document(error: Exception) -> dict[str, object]:
    if isinstance(error, (QAError, ContractError)):
        return error.to_dict()
    return {
        "code": "QA_INTERNAL_ERROR",
        "category": "internal",
        "retryable": False,
        "message": "QA review failed; inspect the sanitized trace reference",
        "field_paths": [],
        "details": {"trace_ref": "qa-cli-internal"},
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request_path = LegacyPathGuard().assert_allowed(args.request)
        document = parse_json_object(request_path.read_bytes())
        if document.get("command") != args.command:
            raise QAError(
                QAErrorCode.QA_INPUT_INVALID,
                "validation",
                "CLI command and request command must match",
                field_paths=("command",),
            )
        request = ReviewRequest.from_mapping(document)
        if request.context.get("cancelled") is True:
            raise QAError(
                QAErrorCode.QA_CANCELLED,
                "state",
                "QA review was cancelled before evaluation",
                field_paths=("context.cancelled",),
            )
        artifacts = review(request)
        QAOutputWriter(args.output_dir).write(artifacts)
    except (QAError, ContractError, OSError, ValueError) as exc:
        sys.stderr.write(canonical_json(_error_document(exc)) + "\n")
        return 64

    sys.stdout.write(
        json.dumps(
            {
                "interface_version": "1.0.0",
                "outcome": artifacts.outcome.value,
                "output_dir": str(Path(args.output_dir).resolve(strict=False)),
            },
            sort_keys=True,
        )
        + "\n"
    )
    return {
        ReviewOutcome.PASS: 0,
        ReviewOutcome.FAIL: 2,
        ReviewOutcome.NEEDS_REVIEW: 3,
    }[artifacts.outcome]


if __name__ == "__main__":
    raise SystemExit(main())
