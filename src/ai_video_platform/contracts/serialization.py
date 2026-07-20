"""Canonical JSON and content hashing for immutable contract artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any
from uuid import UUID

from .errors import ContractError, ErrorCategory, ErrorCode


DEFAULT_MAX_JSON_BYTES = 1_048_576


class _DuplicateKeyError(ValueError):
    pass


def freeze_json(value: Any) -> Any:
    """Return an immutable snapshot of a JSON-compatible value."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_json(nested) for key, nested in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item) for item in value)
    return value


def thaw_json(value: Any) -> Any:
    """Return a mutable JSON-compatible projection of an immutable snapshot."""
    if isinstance(value, Mapping):
        return {key: thaw_json(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [thaw_json(item) for item in value]
    return value


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_non_finite_number(value: str) -> None:
    del value
    raise ValueError


def _json_input_error(message: str) -> ContractError:
    return ContractError(
        ErrorCode.CONTRACT_VALIDATION_FAILED,
        ErrorCategory.VALIDATION,
        message,
        field_paths=("json",),
    )


def parse_json_object(
    document: str | bytes | bytearray,
    *,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> dict[str, Any]:
    """Parse one bounded UTF-8 JSON object and reject ambiguous input."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    try:
        if isinstance(document, str):
            encoded = document.encode("utf-8")
            text = document
        else:
            encoded = bytes(document)
            text = encoded.decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise _json_input_error("Contract input must be valid UTF-8 JSON") from exc
    if len(encoded) > max_bytes:
        raise _json_input_error("Contract input exceeds the configured size limit")
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_non_finite_number,
        )
    except (_DuplicateKeyError, json.JSONDecodeError, ValueError) as exc:
        raise _json_input_error("Contract input is not an unambiguous JSON object") from exc
    if not isinstance(parsed, dict):
        raise _json_input_error("Contract input root must be a JSON object")
    return parsed


def _json_default(value: object) -> object:
    contract_projection = getattr(value, "__contract_json__", None)
    if callable(contract_projection):
        return contract_projection()
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: getattr(value, item.name) for item in fields(value)}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime values must be timezone-aware")
        utc_value = value.astimezone(timezone.utc)
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    )


def content_digest(value: object) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
