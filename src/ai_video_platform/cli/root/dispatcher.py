"""Thin root CLI dispatcher for the registered Storyboard Artifact Chain targets.

The dispatcher only translates the canonical root command shape into each
owner's public CLI shape.  Business validation and artifact production remain
owned by the individual Skills.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from ai_video_platform.skills.video_generation import (
    FakeVideoProviderAdapter,
    InMemoryVideoExecutionLedger,
    NetworkBlockedVideoProviderAdapter,
    RejectingVideoProviderAdapter,
    VideoGenerationInterface,
    GenerationError,
)


_ROUTES = {
    ("storyboard", "derive-production-panels"),
    ("image-panel", "generate-panels"),
    ("video-planning", "build-storyboard-master"),
    ("video-generation", "run"),
    ("qa-review", "review-artifact"),
    ("qa-review", "review-composition"),
}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parse(argv: Sequence[str] | None) -> tuple[str, str, list[str]]:
    parser = _Parser(prog="ai-video-platform", add_help=True)
    parser.add_argument("namespace")
    parser.add_argument("command")
    parser.add_argument("remainder", nargs=argparse.REMAINDER)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if (args.namespace, args.command) not in _ROUTES:
        raise ValueError("unsupported root CLI target")
    return args.namespace, args.command, list(args.remainder)


def _input_path(args: Sequence[str]) -> Path:
    try:
        index = list(args).index("--input")
        return Path(args[index + 1])
    except (ValueError, IndexError) as exc:
        raise ValueError("root CLI route requires --input") from exc


def _output_arg(args: Sequence[str]) -> str:
    values = list(args)
    try:
        return values[values.index("--output-dir") + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("root CLI route requires --output-dir") from exc


def _run_video_generation(args: Sequence[str]) -> int:
    parser = _Parser(prog="ai-video-platform video-generation run", add_help=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--adapter", choices=("rejecting", "network-blocked", "fake"), default="rejecting")
    parsed = parser.parse_args(list(args))
    request = json.loads(parsed.input.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("video-generation input must be a JSON object")
    adapters = {
        "rejecting": RejectingVideoProviderAdapter,
        "network-blocked": NetworkBlockedVideoProviderAdapter,
        "fake": FakeVideoProviderAdapter,
    }
    interface = VideoGenerationInterface(
        adapter=adapters[parsed.adapter](),
        ledger=InMemoryVideoExecutionLedger(),
    )
    try:
        result = interface.submit_video(request)
    except GenerationError as error:
        print(json.dumps({"ok": False, "exit_code": 2, "error": error.to_dict()}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "exit_code": 0, "result": result}, sort_keys=True))
    return 0


def dispatch(namespace: str, command: str, args: Sequence[str]) -> int:
    if namespace == "video-generation":
        return _run_video_generation(args)

    if namespace == "storyboard":
        from ai_video_platform.skills.storyboard.cli import main as owner_main
        return owner_main([command, *args])
    if namespace == "image-panel":
        from ai_video_platform.skills.product_image_panel_generation.cli import main as owner_main
        return owner_main([command, *args])
    if namespace == "video-planning":
        from ai_video_platform.skills.storyboard_master_video_planning.cli import main as owner_main
        input_path = _input_path(args)
        return owner_main([command, str(input_path)])
    from ai_video_platform.skills.qa_review.cli import main as owner_main
    return owner_main([command, "--request", str(_input_path(args)), "--output-dir", _output_arg(args)])


def main(argv: Sequence[str] | None = None) -> int:
    try:
        namespace, command, args = _parse(argv)
        return dispatch(namespace, command, args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "exit_code": 2, "error": {"code": "ROOT_CLI_INPUT_INVALID", "message": str(error)}}, sort_keys=True))
        return 2


__all__ = ["dispatch", "main"]
