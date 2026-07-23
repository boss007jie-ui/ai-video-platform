"""Skill-local CLI for inspect, product-image, and panel commands."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Sequence, TextIO

from ai_video_platform.contracts import ContractError, parse_json_object
from ai_video_platform.contracts.serialization import canonical_json
from .adapters import FakeImageProviderAdapter, ImageProviderAdapter, RejectingImageProviderAdapter
from .codec import generation_request_from_mapping, model_profile_from_mapping
from .cli_ledger import CliExecutionLedger, assert_task_workspace
from .errors import ImagePanelError, ImagePanelErrorCode
from .models import GenerationCommand, GenerationOutcome, GenerationStatus
from .service import ImagePanelService
from .yunwu_adapters import YunwuImage2Adapter, YunwuNanoBananaAdapter


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
    parser.add_argument(
        "--adapter",
        choices=("rejecting", "fake", "yunwu-nano-banana", "yunwu-image2"),
        default="rejecting",
    )
    parser.add_argument("--output-dir")
    return parser


def _adapter_from_name(name: str) -> ImageProviderAdapter:
    if name == "fake":
        return FakeImageProviderAdapter()
    if name == "rejecting":
        return RejectingImageProviderAdapter()
    adapter_type = {
        "yunwu-nano-banana": YunwuNanoBananaAdapter,
        "yunwu-image2": YunwuImage2Adapter,
    }.get(name)
    if adapter_type is None:
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "CLI adapter is invalid",
            field_paths=("argv",),
        )
    try:
        return adapter_type.from_environment()
    except ValueError as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
            "YUNWU_API_KEY is required",
            category="authorization",
            field_paths=("YUNWU_API_KEY",),
        ) from exc


def _resolve_output_directory(input_path: Path, raw_output_dir: str | None) -> Path:
    workspace = input_path.parent.resolve()
    output_dir = Path(raw_output_dir).resolve() if raw_output_dir else workspace
    try:
        output_dir.relative_to(workspace)
    except ValueError as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "CLI output directory must stay within the input task workspace",
            category="authorization",
            field_paths=("output_dir",),
        ) from exc
    if output_dir.exists() and not output_dir.is_dir():
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "CLI output directory is not a directory",
            field_paths=("output_dir",),
        )
    return output_dir


def _persist_yunwu_artifact(
    adapter: YunwuNanoBananaAdapter | YunwuImage2Adapter,
    *,
    output_dir: Path,
    request_hash: str,
) -> dict[str, object]:
    asset = adapter.last_asset
    digest = hashlib.sha256(asset.content).hexdigest()
    request_token = hashlib.sha256(request_hash.encode("utf-8")).hexdigest()[:16]
    output_path = output_dir / f"yunwu-{request_token}-{digest[:16]}.png"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            if output_path.read_bytes() != asset.content:
                raise ImagePanelError(
                    ImagePanelErrorCode.CONTRACT_INVALID,
                    "CLI output artifact conflicts with an existing file",
                    category="conflict",
                    field_paths=("output_dir",),
                )
        else:
            with output_path.open("xb") as stream:
                stream.write(asset.content)
    except ImagePanelError:
        raise
    except OSError as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "CLI output artifact could not be persisted",
            field_paths=("output_dir",),
            details={"cause_type": type(exc).__name__},
        ) from exc
    return {
        "path": str(output_path),
        "provider_asset_id": asset.provider_asset_id,
        "content_type": asset.content_type,
        "byte_size": len(asset.content),
        "sha256": digest,
        "width": asset.width,
        "height": asset.height,
    }


def _outcome_mapping(
    outcome: GenerationOutcome,
    *,
    adapter: ImageProviderAdapter,
    artifact_receipt: dict[str, object] | None = None,
) -> dict:
    payload = {
        "status": outcome.status.value,
        "replayed": outcome.replayed,
        "generation_record": json.loads(canonical_json(outcome.generation_record)),
        "asset_manifest": outcome.asset_manifest.to_dict(),
        "feedback_event": outcome.feedback_event.to_dict(),
        "execution_event": outcome.execution_event.to_dict(),
        "provider_smoke": "NOT_AUTHORIZED",
    }
    if isinstance(adapter, (YunwuNanoBananaAdapter, YunwuImage2Adapter)):
        try:
            receipt = adapter.last_receipt
        except RuntimeError:
            payload["provider_network_performed"] = False
        else:
            payload["provider_smoke"] = (
                "PASS" if outcome.status is GenerationStatus.COMPLETED else "FAIL"
            )
            payload["provider_network_performed"] = receipt.provider_network_performed
            payload["provider_receipt"] = receipt.to_dict()
        if artifact_receipt is not None:
            payload["artifact_receipt"] = artifact_receipt
    return payload


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
        output_dir = _resolve_output_directory(input_path, args.output_dir)
        if args.command == GenerationCommand.INSPECT_GENERATION_REQUEST.value:
            adapter = _adapter_from_name(args.adapter)
            service = ImagePanelService(
                provider=adapter,
                profiles=(profile,),
                max_concurrency=profile.max_concurrency,
            )
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
            adapter = _adapter_from_name(args.adapter)
            service = ImagePanelService(
                provider=adapter,
                profiles=(profile,),
                max_concurrency=profile.max_concurrency,
            )
            if args.command == GenerationCommand.GENERATE_PRODUCT_IMAGE.value:
                outcome = service.generate_product_image(request)
            else:
                outcome = service.generate_panel(request)
            artifact_receipt = None
            if (
                isinstance(adapter, (YunwuNanoBananaAdapter, YunwuImage2Adapter))
                and outcome.status is GenerationStatus.COMPLETED
            ):
                artifact_receipt = _persist_yunwu_artifact(
                    adapter,
                    output_dir=output_dir,
                    request_hash=request.request_hash,
                )
            outcome_mapping = _outcome_mapping(
                outcome,
                adapter=adapter,
                artifact_receipt=artifact_receipt,
            )
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
