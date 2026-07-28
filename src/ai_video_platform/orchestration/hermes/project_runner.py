"""Minimal local step runner for Hermes project execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


STATE_VERSION = "1.0.0"
STATE_RELATIVE_PATH = Path(".hermes") / "project_run.json"
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

_PRODUCTION_TRUNK = (
    ("product_context", "product-knowledge", "build-product-context"),
    ("storyboard", "storyboard", "derive-production-panels"),
    ("panel_generation", "product-image-panel-generation", "generate-panels"),
    ("video_planning", "storyboard-master-video-planning", "build-storyboard-master"),
    ("qa_review", "qa-review", "review-composition"),
    ("video_generation", "video-generation", "run"),
)
_RECIPES = {
    "product_first": _PRODUCTION_TRUNK,
    "reference_video_first": (
        ("reference_analysis", "reference-analysis", "analyze-storyboard"),
        *_PRODUCTION_TRUNK,
    ),
}


class RunnerError(ValueError):
    """A stable local Runner rejection."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class HermesProjectRunner:
    """Persist and enforce one fixed next step without executing a Skill."""

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).resolve(strict=False)
        self.state_path = self.workspace / STATE_RELATIVE_PATH

    def start(self, *, project_id: str, entry_mode: str) -> dict[str, object]:
        if _PROJECT_ID.fullmatch(project_id) is None:
            raise RunnerError("project_id is invalid")
        recipe = _RECIPES.get(entry_mode)
        if recipe is None:
            raise RunnerError("entry_mode must be product_first or reference_video_first")
        if self.workspace.exists() and (self.workspace.is_symlink() or not self.workspace.is_dir()):
            raise RunnerError("workspace is invalid")
        self.workspace.mkdir(parents=True, exist_ok=True)
        state_dir = self.state_path.parent
        state_dir.mkdir(exist_ok=True)
        if self.state_path.exists():
            raise RunnerError("project run already exists")
        state: dict[str, object] = {
            "schema_version": STATE_VERSION,
            "project_id": project_id,
            "entry_mode": entry_mode,
            "status": "running",
            "current_index": 0,
            "completed_steps": [],
            "steps": [
                {
                    "step_id": step_id,
                    "skill_id": skill_id,
                    "command": command,
                    "status": "pending",
                    "artifact_refs": [],
                    "result_digest": None,
                }
                for step_id, skill_id, command in recipe
            ],
        }
        self._write_new(state)
        return self._public(state)

    def status(self) -> dict[str, object]:
        return self._public(self._read())

    def authorize(self, *, skill_id: str, command: str) -> dict[str, object]:
        state = self._read()
        current = self._current(state)
        if current is None or current["skill_id"] != skill_id or current["command"] != command:
            raise RunnerError("requested Skill is not the current project step")
        return dict(current)

    def complete(self, completion: Mapping[str, object]) -> dict[str, object]:
        if set(completion) != {"step_id", "skill_id", "command", "status", "artifact_refs", "result"}:
            raise RunnerError("completion fields are invalid")
        state = self._read()
        current = self._current(state)
        if current is None:
            raise RunnerError("project run is already complete")
        if (
            completion.get("step_id") != current["step_id"]
            or completion.get("skill_id") != current["skill_id"]
            or completion.get("command") != current["command"]
        ):
            raise RunnerError("completion does not match the current project step")
        if completion.get("status") != "completed":
            raise RunnerError("only a completed current step can advance")
        artifacts = completion.get("artifact_refs")
        if (
            not isinstance(artifacts, list)
            or not artifacts
            or any(not isinstance(item, str) or not item.strip() for item in artifacts)
        ):
            raise RunnerError("completion requires artifact references")
        result = completion.get("result")
        if not isinstance(result, Mapping) or not self._result_succeeded(result):
            raise RunnerError("Skill result is not successful")
        self._validate_execution_event(result, expected_skill_id=str(current["skill_id"]))
        try:
            result_digest = _digest(result)
        except (TypeError, ValueError):
            raise RunnerError("Skill result is not finite JSON") from None

        steps = state["steps"]
        index = int(state["current_index"])
        completed_step = dict(steps[index])
        completed_step.update({
            "status": "completed",
            "artifact_refs": list(artifacts),
            "result_digest": result_digest,
        })
        steps[index] = completed_step
        completed_steps = list(state["completed_steps"])
        completed_steps.append(str(current["step_id"]))
        state["completed_steps"] = completed_steps
        state["current_index"] = index + 1
        if index + 1 == len(steps):
            state["status"] = "completed"
        self._replace(state)
        return self._public(state)

    @staticmethod
    def _result_succeeded(result: Mapping[str, object]) -> bool:
        status = result.get("status")
        outcome = result.get("outcome")
        return bool(
            result.get("ok") is True
            or (isinstance(status, str) and status.upper() in {"COMPLETED", "SUCCEEDED", "READY"})
            or (isinstance(outcome, str) and outcome.upper() == "PASS")
        )

    @staticmethod
    def _validate_execution_event(result: Mapping[str, object], *, expected_skill_id: str) -> None:
        event: object = result.get("execution_event", result.get("skill_execution_event"))
        nested = result.get("result")
        if event is None and isinstance(nested, Mapping):
            event = nested.get("execution_event", nested.get("skill_execution_event"))
        if event is None:
            return
        if isinstance(event, Mapping) and isinstance(event.get("payload"), Mapping):
            event = event["payload"]
        if not isinstance(event, Mapping):
            raise RunnerError("Skill execution event is invalid")
        if (
            event.get("skill_id") != expected_skill_id
            or event.get("event_type") != "completed"
            or event.get("status") not in {"completed", "succeeded"}
        ):
            raise RunnerError("Skill execution event does not match the current step")

    def _read(self) -> dict[str, object]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise RunnerError("project run state is unavailable") from None
        required_state = {
            "schema_version", "project_id", "entry_mode", "status", "current_index", "completed_steps", "steps",
        }
        if not isinstance(value, dict) or set(value) != required_state or value.get("schema_version") != STATE_VERSION:
            raise RunnerError("project run state is invalid")
        recipe = _RECIPES.get(str(value.get("entry_mode")))
        steps = value.get("steps")
        if (
            recipe is None
            or not isinstance(steps, list)
            or len(steps) != len(recipe)
            or not isinstance(value.get("current_index"), int)
            or not 0 <= int(value["current_index"]) <= len(steps)
        ):
            raise RunnerError("project run state is invalid")
        index = int(value["current_index"])
        completed_steps = value.get("completed_steps")
        if (
            not isinstance(completed_steps, list)
            or completed_steps != [item[0] for item in recipe[:index]]
            or value.get("status") != ("completed" if index == len(steps) else "running")
        ):
            raise RunnerError("project run state is inconsistent")
        required_step = {"step_id", "skill_id", "command", "status", "artifact_refs", "result_digest"}
        for position, (step, expected) in enumerate(zip(steps, recipe, strict=True)):
            if (
                not isinstance(step, dict)
                or set(step) != required_step
                or tuple(step.get(key) for key in ("step_id", "skill_id", "command")) != expected
            ):
                raise RunnerError("project run recipe was modified")
            artifacts = step.get("artifact_refs")
            digest = step.get("result_digest")
            if position < index:
                if (
                    step.get("status") != "completed"
                    or not isinstance(artifacts, list)
                    or not artifacts
                    or not isinstance(digest, str)
                    or _DIGEST.fullmatch(digest) is None
                ):
                    raise RunnerError("project run state is inconsistent")
            elif step.get("status") != "pending" or artifacts != [] or digest is not None:
                raise RunnerError("project run state is inconsistent")
        return value

    @staticmethod
    def _current(state: Mapping[str, object]) -> dict[str, object] | None:
        steps = state["steps"]
        index = int(state["current_index"])
        return None if index == len(steps) else dict(steps[index])

    @classmethod
    def _public(cls, state: Mapping[str, object]) -> dict[str, object]:
        return {
            **dict(state),
            "current_step": cls._current(state),
        }

    def _write_new(self, state: Mapping[str, object]) -> None:
        try:
            with self.state_path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(_canonical_json(state) + "\n")
        except FileExistsError:
            raise RunnerError("project run already exists") from None

    def _replace(self, state: Mapping[str, object]) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        if temporary.exists():
            raise RunnerError("project run update is already in progress")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(_canonical_json(state) + "\n")
            temporary.replace(self.state_path)
        finally:
            temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-project-runner")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--workspace", required=True, type=Path)
    start.add_argument("--project-id", required=True)
    start.add_argument("--entry-mode", required=True, choices=tuple(_RECIPES))
    status = subparsers.add_parser("status")
    status.add_argument("--workspace", required=True, type=Path)
    authorize = subparsers.add_parser("authorize")
    authorize.add_argument("--workspace", required=True, type=Path)
    authorize.add_argument("--skill-id", required=True)
    authorize.add_argument("--command", required=True)
    complete = subparsers.add_parser("complete")
    complete.add_argument("--workspace", required=True, type=Path)
    complete.add_argument("--input", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        runner = HermesProjectRunner(args.workspace)
        if args.operation == "start":
            result = runner.start(project_id=args.project_id, entry_mode=args.entry_mode)
        elif args.operation == "status":
            result = runner.status()
        elif args.operation == "authorize":
            result = runner.authorize(skill_id=args.skill_id, command=args.command)
        else:
            raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
            completion = json.loads(raw)
            if not isinstance(completion, dict):
                raise RunnerError("completion input must be a JSON object")
            result = runner.complete(completion)
    except (RunnerError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(_canonical_json({"ok": False, "error": str(error)}))
        return 2
    print(_canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
