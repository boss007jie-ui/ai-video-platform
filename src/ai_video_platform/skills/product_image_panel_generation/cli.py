"""Skill-local CLI for inspect, product-image, and panel commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence, TextIO

from ai_video_platform.contracts import ContractError, parse_json_object
from ai_video_platform.contracts.serialization import canonical_json
from .adapters import FakeImageProviderAdapter, RejectingImageProviderAdapter
from .codec import generation_request_from_mapping, model_profile_from_mapping
from .cli_ledger import CliExecutionLedger, assert_task_workspace
from .errors import ImagePanelError, ImagePanelErrorCode
from .models import GenerationCommand, GenerationOutcome, GenerationStatus
from .service import ImagePanelService


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "CLI arguments are invalid",
            field_paths=("argv",),
            details={"reason": message},
        )


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="product-image-panel-generation", add_help=True)
    parser.add_argument(
        "command",
        choices=[
            GenerationCommand.GENERATE_PRODUCT_IMAGE.value,
            GenerationCommand.GENERATE_PANEL.value,
            GenerationCommand.INSPECT_GENERATION_REQUEST.value,
        ],
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--adapter", choices=("rejecting", "fake"), default="rejecting")
    return parser


def _outcome_mapping(outcome: GenerationOutcome) -> dict:
    return {
        "status": outcome.status.value,
        "replayed": outcome.replayed,
        "generation_record": json.loads(canonical_json(outcome.generation_record)),
        "asset_manifest": outcome.asset_manifest.to_dict(),
        "feedback_event": outcome.feedback_event.to_dict(),
        "execution_event": outcome.execution_event.to_dict(),
        "provider_smoke": "NOT_AUTHORIZED",
    }


def _write(stream: TextIO, payload: dict) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    stream.write("\n")


def main(argv: Sequence[str] | None = None, *, stdout: TextIO | None = None) -> int:
    output = stdout or sys.stdout
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        input_path = assert_task_workspace(Path(args.input)).resolve()
        document = parse_json_object(input_path.read_bytes())
        request = generation_request_from_mapping(document.get("request"))
        profile = model_profile_from_mapping(document.get("model_profile"))
        adapter = FakeImageProviderAdapter() if args.adapter == "fake" else RejectingImageProviderAdapter()
        service = ImagePanelService(
            provider=adapter,
            profiles=(profile,),
            max_concurrency=profile.max_concurrency,
        )
        if args.command == GenerationCommand.INSPECT_GENERATION_REQUEST.value:
            inspection = service.inspect_generation_request(request)
            _write(
                output,
                {
                    "status": "approved",
                    "request_hash": inspection.request_hash,
                    "estimated_max_cost_units": inspection.estimated_max_cost_units,
                    "item_count": inspection.item_count,
                    "profile_id": inspection.profile_id,
                    "provider_smoke": "NOT_AUTHORIZED",
                },
            )
            return 0
        if args.command != request.command.value:
            raise ImagePanelError(
                ImagePanelErrorCode.SKILL_BINDING_INVALID,
                "CLI command does not match request command",
                field_paths=("command", "request.command"),
            )
        ledger = CliExecutionLedger(input_path.parent)
        replay = ledger.begin(request.idempotency_key, request.request_hash)
        if replay is not None:
            _write(output, replay)
            return 0 if replay.get("status") == GenerationStatus.COMPLETED.value else 3
        try:
            if args.command == GenerationCommand.GENERATE_PRODUCT_IMAGE.value:
                outcome = service.generate_product_image(request)
            else:
                outcome = service.generate_panel(request)
            outcome_mapping = _outcome_mapping(outcome)
            ledger.commit(request.idempotency_key, request.request_hash, outcome_mapping)
        except BaseException:
            ledger.abort()
            raise
        _write(output, outcome_mapping)
        return 0 if outcome.status is GenerationStatus.COMPLETED else 3
    except ImagePanelError as exc:
        _write(output, {"status": "error", "error": exc.to_dict(), "provider_smoke": "NOT_AUTHORIZED"})
        return 2
    except ContractError as exc:
        wrapped = ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "Foundation contract input was rejected",
            field_paths=("input",),
            details={"contract_error_code": exc.code.value},
        )
        _write(output, {"status": "error", "error": wrapped.to_dict(), "provider_smoke": "NOT_AUTHORIZED"})
        return 2
    except (OSError, KeyError, TypeError, ValueError) as exc:
        wrapped = ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "CLI input could not be loaded",
            field_paths=("input",),
            details={"cause_type": type(exc).__name__},
        )
        _write(output, {"status": "error", "error": wrapped.to_dict(), "provider_smoke": "NOT_AUTHORIZED"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
