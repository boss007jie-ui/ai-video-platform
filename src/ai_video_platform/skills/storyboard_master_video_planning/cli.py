"""Owner-local public CLI for canonical Video Planning artifacts."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence

from .errors import PlanningError, PlanningErrorCode
from .interface import VideoPlanningInterface
from .models import canonical_json

_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def _write_outputs(output_root: Path, result: Mapping[str, object]) -> None:
    root = output_root / "video_generation_storyboard"
    root.mkdir(parents=True, exist_ok=False)
    names = {
        "video_generation_storyboard_master": "video_generation_storyboard_master.json",
        "shot_motion_plan": "shot_motion_plan.json", "video_execution_package": "video_execution_package.json",
        "first_frame_mapping": "first_frame_mapping.json", "reference_role_mapping": "reference_role_mapping.json",
    }
    for key, name in names.items():
        (root / name).write_text(json.dumps(result["artifacts"][key], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "video_planning_provenance.json").write_text(json.dumps(result["provenance"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "video_storyboard_master.png").write_bytes(_PNG)


def run_cli(command: str, document: Mapping[str, object]) -> dict[str, object]:
    if command != "build-storyboard-master":
        return {"ok": False, "exit_code": 2, "error": PlanningError(PlanningErrorCode.INVALID_INPUT, "Unsupported command").to_dict()}
    try:
        result = VideoPlanningInterface().build_storyboard_master(document)
        output_root = document.get("output_root")
        if output_root is not None:
            if not isinstance(output_root, str) or not output_root:
                raise PlanningError(PlanningErrorCode.INVALID_INPUT, "output_root must be a path string")
            _write_outputs(Path(output_root), result)
        return {"ok": True, "exit_code": 0, "result": result}
    except (PlanningError, OSError) as error:
        failure = error if isinstance(error, PlanningError) else PlanningError(PlanningErrorCode.INVALID_INPUT, "Output tree could not be written")
        return {"ok": False, "exit_code": 2, "error": failure.to_dict()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="video-planning")
    parser.add_argument("command", choices=("build-storyboard-master",))
    parser.add_argument("input")
    try:
        args = parser.parse_args(argv)
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError
        result = run_cli(args.command, document)
    except (OSError, ValueError, json.JSONDecodeError, SystemExit):
        result = {"ok": False, "exit_code": 2, "error": PlanningError(PlanningErrorCode.INVALID_INPUT, "Input must be a readable JSON object").to_dict()}
    print(canonical_json(result))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
