"""Standalone Product Knowledge CLI owned by the Skill."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence, TextIO

from ai_video_platform.contracts.errors import ContractError, ErrorCategory
from ai_video_platform.contracts.serialization import canonical_json, parse_json_object
from ai_video_platform.contracts.validation import validate_payload
from ai_video_platform.core.guards import LegacyPathGuard
from ai_video_platform.core.ids import uuid7

from .adapters.filesystem import FilesystemProductLibrary
from .application.service import ProductKnowledgeService
from .errors import ProductKnowledgeError, ProductKnowledgeErrorCode


SKILL_VERSION = "1.0.0"
COMMANDS = (
    "identify-product",
    "ingest-product",
    "match-product",
    "create-product",
    "create-sku",
    "organize-assets",
    "resolve-conflict",
    "build-product-context",
    "build-product-review-context",
    "record-feedback",
    "confirm-feedback",
    "consolidate-learning",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def execute_command(
    service: ProductKnowledgeService,
    command: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    handlers = {
        "identify-product": service.identify_product,
        "ingest-product": service.ingest_product,
        "match-product": service.match_product,
        "create-product": service.create_product,
        "create-sku": service.create_sku,
        "organize-assets": service.organize_assets,
        "resolve-conflict": service.resolve_conflict,
        "build-product-context": service.build_product_context,
        "build-product-review-context": service.build_product_review_context,
        "record-feedback": service.record_feedback,
        "confirm-feedback": service.confirm_feedback,
        "consolidate-learning": service.consolidate_learning,
    }
    return handlers[command](request)


def _execution_event(
    request: Mapping[str, Any],
    *,
    event_type: str,
    status: str,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "execution_id": str(uuid7()),
        "task_id": str(request.get("task_id", "standalone-product-knowledge")),
        "skill_id": "product-knowledge",
        "event_type": event_type,
        "sequence": 1,
        "occurred_at": _utc_now(),
        "status": status,
        "input_contract_refs": list(request.get("input_contract_refs", [])),
        "output_contract_refs": [],
    }
    if error is not None:
        payload["error"] = dict(error)
    return validate_payload(
        "avp.contract.skill-execution-event",
        payload,
        producer_component_id="product-knowledge",
        producer_agent="skill",
    ).__contract_json__()


def _exit_for_product_error(error: ProductKnowledgeError) -> int:
    if error.code in {
        ProductKnowledgeErrorCode.PRODUCT_LIBRARY_WRITE_FORBIDDEN,
        ProductKnowledgeErrorCode.REVIEW_AUTHORITY_INSUFFICIENT,
    }:
        return 4
    if error.code in {
        ProductKnowledgeErrorCode.PRODUCT_MATCH_AMBIGUOUS,
        ProductKnowledgeErrorCode.IDEMPOTENCY_MISMATCH,
        ProductKnowledgeErrorCode.LIBRARY_VERSION_CONFLICT,
        ProductKnowledgeErrorCode.AGGREGATE_VERSION_CONFLICT,
        ProductKnowledgeErrorCode.APPROVAL_SUBJECT_MISMATCH,
    }:
        return 3
    if error.code in {
        ProductKnowledgeErrorCode.PRODUCT_NOT_FOUND,
        ProductKnowledgeErrorCode.SKU_NOT_FOUND,
        ProductKnowledgeErrorCode.FEEDBACK_NOT_FOUND,
        ProductKnowledgeErrorCode.CONFLICT_NOT_FOUND,
        ProductKnowledgeErrorCode.FEEDBACK_NOT_CONFIRMED,
        ProductKnowledgeErrorCode.IDEMPOTENCY_RESTORED_OUT,
    }:
        return 5
    if error.code is ProductKnowledgeErrorCode.INTERNAL_ERROR:
        return 70
    return 2


def _write_json(stream: TextIO, value: Mapping[str, Any]) -> None:
    stream.write(canonical_json(value) + "\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    del stderr
    parser = argparse.ArgumentParser(prog="product-knowledge")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--library", required=True)
    parser.add_argument("--input", default="-", help="UTF-8 JSON object path or '-' for stdin")
    parser.add_argument("--version", action="version", version=SKILL_VERSION)
    args = parser.parse_args(list(argv) if argv is not None else None)

    request: dict[str, Any] = {}
    try:
        if args.input == "-":
            document = stdin.read()
        else:
            guard = LegacyPathGuard()
            input_path = guard.assert_allowed(Path(args.input)).resolve()
            guard.assert_allowed(input_path)
            document = input_path.read_bytes()
        request = parse_json_object(document)
        library = FilesystemProductLibrary(Path(args.library))
        result = execute_command(ProductKnowledgeService(library), args.command, request)
        _write_json(
            stdout,
            {
                "ok": True,
                "skill_id": "product-knowledge",
                "skill_version": SKILL_VERSION,
                "result": result,
                "execution_event": _execution_event(request, event_type="completed", status="succeeded"),
            },
        )
        return 0
    except ProductKnowledgeError as error:
        public_error = error.to_dict()
        _write_json(
            stdout,
            {
                "ok": False,
                "skill_id": "product-knowledge",
                "skill_version": SKILL_VERSION,
                "error": public_error,
                "execution_event": _execution_event(
                    request,
                    event_type="failed",
                    status="failed",
                    error=public_error,
                ),
            },
        )
        return _exit_for_product_error(error)
    except ContractError as error:
        public_error = error.to_dict()
        _write_json(
            stdout,
            {
                "ok": False,
                "skill_id": "product-knowledge",
                "skill_version": SKILL_VERSION,
                "error": public_error,
                "execution_event": _execution_event(
                    request,
                    event_type="failed",
                    status="failed",
                    error=public_error,
                ),
            },
        )
        if error.category is ErrorCategory.AUTHORIZATION:
            return 4
        if error.category is ErrorCategory.CONFLICT:
            return 3
        return 2
    except (KeyError, TypeError, ValueError) as error:
        del error
        public_error = ProductKnowledgeError(
            ProductKnowledgeErrorCode.VALIDATION_FAILED,
            "Command input is missing or invalid",
        ).to_dict()
        _write_json(
            stdout,
            {
                "ok": False,
                "skill_id": "product-knowledge",
                "skill_version": SKILL_VERSION,
                "error": public_error,
                "execution_event": _execution_event(request, event_type="failed", status="failed", error=public_error),
            },
        )
        return 2
    except Exception as error:
        del error
        public_error = ProductKnowledgeError(
            ProductKnowledgeErrorCode.INTERNAL_ERROR,
            "Product Knowledge command failed",
        ).to_dict()
        _write_json(
            stdout,
            {
                "ok": False,
                "skill_id": "product-knowledge",
                "skill_version": SKILL_VERSION,
                "error": public_error,
                "execution_event": _execution_event(request, event_type="failed", status="failed", error=public_error),
            },
        )
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
