"""Module CLI for the offline Planning public interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence

from .errors import PlanningError
from .interface import VideoPlanningInterface
from .models import canonical_json


def run_cli(command: str, document: Mapping[str, object]) -> dict[str, object]:
    interface = VideoPlanningInterface()
    commands = {
        "compose-storyboard-master": interface.compose_storyboard_master,
        "build-video-plan": interface.build_video_plan,
        "validate-video-plan": interface.validate_video_plan,
    }
    if command not in commands:
        return {"ok": False, "exit_code": 2, "error": {"code": "INVALID_INPUT", "category": "validation", "retryable": False, "message": "Unsupported command", "field_paths": ["command"], "details": {}}}
    try:
        return {"ok": True, "exit_code": 0, "result": commands[command](document)}
    except PlanningError as error:
        return {"ok": False, "exit_code": 2, "error": error.to_dict()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="storyboard-master-video-planning")
    parser.add_argument("command", choices=("compose-storyboard-master", "build-video-plan", "validate-video-plan"))
    parser.add_argument("input", help="UTF-8 JSON request file or '-' for stdin")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError
        result = run_cli(args.command, document)
    except (OSError, ValueError, json.JSONDecodeError):
        result = {"ok": False, "exit_code": 2, "error": {"code": "INVALID_INPUT", "category": "validation", "retryable": False, "message": "Input must be a readable UTF-8 JSON object", "field_paths": ["input"], "details": {}}}
    print(canonical_json(result))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
