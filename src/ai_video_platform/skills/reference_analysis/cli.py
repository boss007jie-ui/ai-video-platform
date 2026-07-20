"""Skill-local JSON CLI for deterministic Reference Analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .errors import SkillError
from .interface import analyze_reference, compare_result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reference-analysis")
    parser.add_argument("command", choices=("analyze-reference", "compare-result"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        request = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
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
