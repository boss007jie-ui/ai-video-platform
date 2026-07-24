"""Skill-local JSON CLI for deterministic Reference Analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .errors import ErrorCode, SkillError
from .interface import analyze_reference, compare_result
from .storyboard import analyze_storyboard


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reference-analysis")
    parser.add_argument("command", choices=("analyze-reference", "compare-result", "analyze-storyboard"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)
    try:
        request = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
        if arguments.command == "analyze-storyboard":
            if arguments.output is not None:
                raise SkillError(
                    ErrorCode.VALIDATION_FAILED,
                    "analyze-storyboard always publishes to reference_analysis",
                    field_paths=("output",),
                )
            result = analyze_storyboard(request, workspace=Path(arguments.workspace))
        else:
            if not arguments.output:
                raise SkillError(
                    ErrorCode.VALIDATION_FAILED,
                    "output is required for this command",
                    field_paths=("output",),
                )
            operation = analyze_reference if arguments.command == "analyze-reference" else compare_result
            result = operation(request, workspace=Path(arguments.workspace), output_path=arguments.output)
    except SkillError as exc:
        print(json.dumps({"status": "ERROR", "error": exc.to_dict()}, ensure_ascii=False, sort_keys=True))
        return 2
    except (OSError, ValueError, json.JSONDecodeError):
        print(json.dumps({
            "status": "ERROR",
            "error": {
                "code": "REFERENCE_ANALYSIS_INPUT_FAILED",
                "message": "Input could not be read or parsed",
                "field_paths": [],
                "retryable": False,
                "details": {},
            },
        }, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
