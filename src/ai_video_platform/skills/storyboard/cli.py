"""Machine-readable CLI adapter for the independent Storyboard Interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

from ai_video_platform.contracts.envelope import ContractEnvelope, ProducerIdentity
from ai_video_platform.contracts.errors import ContractError
from ai_video_platform.contracts.serialization import DEFAULT_MAX_JSON_BYTES, parse_json_object, thaw_json

from .interface import StoryboardArtifact, StoryboardError, StoryboardRequest, StoryboardResult, StoryboardService
from .state import FileVersionStore, VersionStoreError


class _MachineArgumentParser(argparse.ArgumentParser):
    """Keep CLI misuse on the same stable JSON error boundary as request errors."""

    def error(self, message: str) -> None:
        raise StoryboardError(
            "STORYBOARD_COMMAND_UNSUPPORTED",
            "validation",
            "CLI command arguments are invalid",
            field_paths=("command",),
        )


def _envelope(value: object, field_name: str) -> ContractEnvelope:
    if not isinstance(value, Mapping):
        raise StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "CLI ContractEnvelope input must be an object",
            field_paths=(field_name,),
        )
    try:
        producer = value["producer"]
        created_at = str(value["created_at"]).replace("Z", "+00:00")
        return ContractEnvelope(
            contract_type=str(value["contract_type"]),
            schema_version=str(value["schema_version"]),
            contract_id=UUID(str(value["contract_id"])),
            created_at=datetime.fromisoformat(created_at),
            producer=ProducerIdentity(
                str(producer["agent"]),
                str(producer["component_id"]),
                str(producer["component_version"]),
            ),
            correlation_id=str(value["correlation_id"]),
            idempotency_key=str(value["idempotency_key"]),
            payload_digest=str(value["payload_digest"]),
            payload=value["payload"],
            task_id=value.get("task_id"),
            causation_id=value.get("causation_id"),
            trace_id=value.get("trace_id"),
            source_contract_ids=tuple(value.get("source_contract_ids", ())),
            source_hashes=tuple(value.get("source_hashes", ())),
            extensions=value.get("extensions", {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "CLI ContractEnvelope input is malformed",
            field_paths=(field_name,),
        ) from exc


def _artifact(value: object) -> StoryboardArtifact | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise StoryboardError("STORYBOARD_INPUT_INVALID", "validation", "prior_artifact must be an object", field_paths=("prior_artifact",))
    try:
        return StoryboardArtifact(
            storyboard_id=str(value["storyboard_id"]),
            version=int(value["version"]),
            task_id=str(value["task_id"]),
            product_id=str(value["product_id"]),
            source_contract_ids=tuple(value["source_contract_ids"]),
            source_hashes=tuple(value["source_hashes"]),
            content_digest=str(value["content_digest"]),
            story=value["story"],
            created_at=str(value["created_at"]),
            supersedes_storyboard_id=value.get("supersedes_storyboard_id"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StoryboardError("STORYBOARD_INPUT_INVALID", "validation", "prior_artifact is malformed", field_paths=("prior_artifact",)) from exc


def _result_payload(result: StoryboardResult) -> dict[str, Any]:
    artifact = None
    if result.artifact is not None:
        artifact = {
            "storyboard_id": result.artifact.storyboard_id,
            "version": result.artifact.version,
            "task_id": result.artifact.task_id,
            "product_id": result.artifact.product_id,
            "source_contract_ids": list(result.artifact.source_contract_ids),
            "source_hashes": list(result.artifact.source_hashes),
            "content_digest": result.artifact.content_digest,
            "story": thaw_json(result.artifact.story),
            "created_at": result.artifact.created_at,
            "supersedes_storyboard_id": result.artifact.supersedes_storyboard_id,
        }
    return {
        "status": result.status,
        "replay_status": result.replay_status,
        "artifact": artifact,
        "asset_manifest": result.asset_manifest.to_dict() if result.asset_manifest else None,
        "feedback_event": result.feedback_event.to_dict() if result.feedback_event else None,
        "execution_event": result.execution_event.to_dict() if result.execution_event else None,
        "error": None,
    }


def _error_payload(error: StoryboardError) -> dict[str, Any]:
    return {
        "status": "failed",
        "replay_status": "not-recorded",
        "artifact": None,
        "error": error.to_dict(),
    }


def run_cli_document(
    document: Mapping[str, Any],
    *,
    service: StoryboardService | None = None,
) -> tuple[int, dict[str, Any]]:
    try:
        command = document.get("command")
        if command not in {"create-storyboard", "revise-storyboard", "validate-continuity"}:
            raise StoryboardError(
                "STORYBOARD_COMMAND_UNSUPPORTED",
                "validation",
                "CLI command must be create-storyboard, revise-storyboard, or validate-continuity",
                field_paths=("command",),
            )
        if command == "validate-continuity":
            selected_service = service or StoryboardService()
            artifact = _artifact(document.get("artifact"))
            if artifact is None:
                raise StoryboardError(
                    "STORYBOARD_INPUT_INVALID",
                    "validation",
                    "validate-continuity requires artifact",
                    field_paths=("artifact",),
                )
            selected_service.validate_continuity(artifact)
            return 0, _result_payload(
                StoryboardResult(status="completed", replay_status="not-applicable", artifact=artifact)
            )
        request = StoryboardRequest(
            command=str(command),
            task_spec=_envelope(document.get("task_spec"), "task_spec"),
            task_context=_envelope(document.get("task_context"), "task_context"),
            product_context=_envelope(document.get("product_context"), "product_context"),
            plan=document.get("plan", {}),
            idempotency_key=str(document.get("idempotency_key", "")),
            expected_version=int(document.get("expected_version", 0)),
            prior_artifact=_artifact(document.get("prior_artifact")),
            reference_manifest=(
                _envelope(document["reference_manifest"], "reference_manifest")
                if document.get("reference_manifest") is not None
                else None
            ),
            cancellation_requested=bool(document.get("cancellation_requested", False)),
        )
        if service is None:
            state_file = document.get("state_file")
            task_workspace = document.get("task_workspace")
            if (
                not isinstance(state_file, str)
                or not state_file.strip()
                or not isinstance(task_workspace, str)
                or not task_workspace.strip()
            ):
                raise StoryboardError(
                    "STORYBOARD_STATE_STORE_REQUIRED",
                    "state",
                    "create/revise CLI requires explicit task_workspace and state_file paths",
                    field_paths=("task_workspace", "state_file"),
                )
            try:
                trusted_workspace = Path(os.environ.get("AVP_TASK_WORKSPACE_ROOT", Path.cwd())).resolve(strict=True)
                provided_workspace = Path(task_workspace).resolve(strict=True)
                if provided_workspace != trusted_workspace:
                    raise VersionStoreError(
                        "STORYBOARD_STATE_PATH_FORBIDDEN",
                        "task_workspace must equal the trusted CLI working directory",
                    )
                selected_service = StoryboardService(
                    version_store=FileVersionStore(Path(state_file), workspace_root=trusted_workspace)
                )
            except (OSError, RuntimeError) as exc:
                raise StoryboardError(
                    "STORYBOARD_STATE_PATH_FORBIDDEN",
                    "state",
                    "Storyboard Task Workspace is unavailable or forbidden",
                    field_paths=("task_workspace", "state_file"),
                ) from exc
            except VersionStoreError as exc:
                raise StoryboardError(
                    exc.code,
                    "state",
                    exc.message,
                    retryable=exc.retryable,
                    field_paths=("task_workspace", "state_file"),
                ) from exc
        else:
            selected_service = service
        return 0, _result_payload(selected_service.execute(request))
    except StoryboardError as exc:
        return 2, _error_payload(exc)
    except (TypeError, ValueError):
        error = StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "CLI input contains an invalid scalar value",
            field_paths=("input",),
        )
        return 2, _error_payload(error)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = _MachineArgumentParser(prog="storyboard", add_help=False)
        parser.add_argument("command", choices=("create-storyboard", "revise-storyboard", "validate-continuity"))
        parser.add_argument("--input", default="-", help="UTF-8 JSON request file or '-' for stdin")
        args = parser.parse_args(argv)
        if args.input == "-":
            raw = sys.stdin.buffer.read(DEFAULT_MAX_JSON_BYTES + 1)
        else:
            with open(args.input, "rb") as handle:
                raw = handle.read(DEFAULT_MAX_JSON_BYTES + 1)
        document = parse_json_object(raw)
        document["command"] = args.command
        exit_code, payload = run_cli_document(document)
    except StoryboardError as exc:
        exit_code, payload = 2, _error_payload(exc)
    except ContractError as exc:
        error = StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            exc.category.value,
            exc.message,
            retryable=exc.retryable,
            field_paths=exc.field_paths,
        )
        exit_code, payload = 2, _error_payload(error)
    except OSError:
        error = StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "reference",
            "CLI input could not be read",
            field_paths=("input",),
        )
        exit_code, payload = 2, _error_payload(error)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
