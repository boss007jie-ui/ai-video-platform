"""Immutable ContractEnvelope implementation for foundation payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Mapping
from uuid import UUID

from ai_video_platform.core.ids import is_uuid7, uuid7

from .registry import get_contract_definition
from .serialization import content_digest, freeze_json, thaw_json


_PRODUCER_AGENTS = {"hermes", "codex", "catpaw", "skill", "system", "human"}
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    utc_value = value.astimezone(timezone.utc)
    if utc_value.microsecond:
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return utc_value.isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ProducerIdentity:
    agent: str
    component_id: str
    component_version: str

    def __post_init__(self) -> None:
        if self.agent not in _PRODUCER_AGENTS:
            raise ValueError(f"Unsupported producer agent: {self.agent}")
        if not self.component_id or not self.component_version:
            raise ValueError("Producer component identity and version are required")

    def to_dict(self) -> dict[str, str]:
        return {
            "agent": self.agent,
            "component_id": self.component_id,
            "component_version": self.component_version,
        }


@dataclass(frozen=True, slots=True)
class ContractEnvelope:
    contract_type: str
    schema_version: str
    contract_id: UUID
    created_at: datetime
    producer: ProducerIdentity
    correlation_id: str
    idempotency_key: str
    payload_digest: str
    payload: Mapping[str, Any]
    task_id: str | None = None
    causation_id: str | None = None
    trace_id: str | None = None
    source_contract_ids: tuple[str, ...] = ()
    source_hashes: tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        get_contract_definition(self.contract_type)
        if not is_uuid7(self.contract_id):
            raise ValueError("contract_id must be UUIDv7")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if not self.correlation_id or not self.idempotency_key:
            raise ValueError("correlation_id and idempotency_key are required")
        if not _DIGEST.fullmatch(self.payload_digest):
            raise ValueError("payload_digest must be lowercase SHA-256")
        if any(not _DIGEST.fullmatch(value) for value in self.source_hashes):
            raise ValueError("source_hashes must contain lowercase SHA-256 digests")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(self, "source_contract_ids", tuple(self.source_contract_ids))
        object.__setattr__(self, "source_hashes", tuple(self.source_hashes))
        object.__setattr__(self, "extensions", freeze_json(self.extensions))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "contract_type": self.contract_type,
            "schema_version": self.schema_version,
            "contract_id": str(self.contract_id),
            "created_at": format_utc(self.created_at),
            "producer": self.producer.to_dict(),
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "payload_digest": self.payload_digest,
            "payload": thaw_json(self.payload),
        }
        optional = {
            "task_id": self.task_id,
            "causation_id": self.causation_id,
            "trace_id": self.trace_id,
            "source_contract_ids": list(self.source_contract_ids) or None,
            "source_hashes": list(self.source_hashes) or None,
            "extensions": thaw_json(self.extensions) or None,
        }
        result.update({key: value for key, value in optional.items() if value is not None})
        return result


def build_envelope(
    *,
    contract_type: str,
    payload: Mapping[str, Any],
    producer: ProducerIdentity,
    correlation_id: str,
    idempotency_key: str,
    contract_id: UUID | None = None,
    created_at: datetime | None = None,
    task_id: str | None = None,
    causation_id: str | None = None,
    trace_id: str | None = None,
    source_contract_ids: tuple[str, ...] = (),
    source_hashes: tuple[str, ...] = (),
    extensions: Mapping[str, Any] | None = None,
) -> ContractEnvelope:
    definition = get_contract_definition(contract_type)
    return ContractEnvelope(
        contract_type=contract_type,
        schema_version=definition.version,
        contract_id=contract_id or uuid7(),
        created_at=created_at or datetime.now(timezone.utc),
        producer=producer,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        payload_digest=content_digest(payload),
        payload=payload,
        task_id=task_id,
        causation_id=causation_id,
        trace_id=trace_id,
        source_contract_ids=source_contract_ids,
        source_hashes=source_hashes,
        extensions=extensions or {},
    )
