"""Machine-readable offline CLI for Video Enhancement."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence

from .errors import EnhancementError, EnhancementErrorCode
from .interface import VideoEnhancementInterface
from .models import canonical_json


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "Invalid CLI arguments", field_paths=("arguments",))


def run_cli(
    command: str,
    document: Mapping[str, object],
    *,
    now: datetime | None = None,
    interface: VideoEnhancementInterface | None = None,
) -> dict[str, object]:
    service = interface or VideoEnhancementInterface()
    try:
        if command == "inspect-enhancement-request":
            result = service.inspect_enhancement_request(document, now=now)
        elif command == "submit-enhancement":
            result = service.submit_enhancement(document, now=now)
        elif command in {
            "poll-enhancement", "cancel-enhancement", "download-enhancement", "recover-enhancement",
        }:
            job_id = document.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "job_id is required", field_paths=("job_id",))
            operation = {
                "poll-enhancement": service.poll_enhancement,
                "cancel-enhancement": service.cancel_enhancement,
                "download-enhancement": service.download_enhancement,
                "recover-enhancement": service.recover_enhancement,
            }[command]
            result = operation(job_id, now=now)
        else:
            raise EnhancementError(EnhancementErrorCode.INVALID_INPUT, "Unsupported command")
        return {"ok": True, "exit_code": 0, "result": result}
    except EnhancementError as error:
        return {"ok": False, "exit_code": 2, "error": error.to_dict()}
    except Exception:
        error = EnhancementError(EnhancementErrorCode.PROVIDER_REJECTED, "Enhancement command failed unexpectedly")
        return {"ok": False, "exit_code": 2, "error": error.to_dict()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _JsonArgumentParser(prog="video-enhancement")
    parser.add_argument("command", choices=(
        "inspect-enhancement-request",
        "submit-enhancement",
        "poll-enhancement",
        "cancel-enhancement",
        "download-enhancement",
        "recover-enhancement",
    ))
    parser.add_argument("input", help="UTF-8 JSON request file or '-' for stdin")
    try:
        args = parser.parse_args(argv)
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError
        result = run_cli(args.command, document)
    except EnhancementError as error:
        result = {"ok": False, "exit_code": 2, "error": error.to_dict()}
    except (OSError, ValueError, json.JSONDecodeError):
        error = EnhancementError(EnhancementErrorCode.INVALID_INPUT, "Input must be a readable UTF-8 JSON object")
        result = {"ok": False, "exit_code": 2, "error": error.to_dict()}
    print(canonical_json(result))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
