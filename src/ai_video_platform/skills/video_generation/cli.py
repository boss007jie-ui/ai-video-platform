"""Machine-readable module CLI for offline Video Generation."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence

from .errors import GenerationError, GenerationErrorCode
from .interface import VideoGenerationInterface
from .models import canonical_json


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise GenerationError(GenerationErrorCode.INVALID_INPUT, "Invalid CLI arguments", field_paths=("arguments",))


def run_cli(command: str, document: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
    if command != "inspect-video-request":
        return {"ok": False, "exit_code": 2, "error": GenerationError(GenerationErrorCode.INVALID_INPUT, "Unsupported command").to_dict()}
    try:
        result = VideoGenerationInterface().inspect_video_request(document, now=now)
        return {"ok": True, "exit_code": 0, "result": result}
    except GenerationError as error:
        return {"ok": False, "exit_code": 2, "error": error.to_dict()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _JsonArgumentParser(prog="video-generation")
    parser.add_argument("command", choices=("inspect-video-request",))
    parser.add_argument("input", help="UTF-8 JSON request file or '-' for stdin")
    try:
        args = parser.parse_args(argv)
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError
        result = run_cli(args.command, document)
    except GenerationError as error:
        result = {"ok": False, "exit_code": 2, "error": error.to_dict()}
    except (OSError, ValueError, json.JSONDecodeError):
        result = {"ok": False, "exit_code": 2, "error": GenerationError(GenerationErrorCode.INVALID_INPUT, "Input must be a readable UTF-8 JSON object").to_dict()}
    print(canonical_json(result))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
