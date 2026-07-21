"""Dependency-free append-only audit primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from ai_video_platform.contracts.serialization import freeze_json

from .ids import uuid7


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: UUID
    correlation_id: str
    sequence: int
    event_type: str
    actor: str
    occurred_at: datetime
    details: Mapping[str, Any]


class InMemoryAuditLedger:
    """Append-only audit sink for offline and fake-adapter execution."""

    def __init__(self) -> None:
        self._events: dict[str, list[AuditEvent]] = {}

    def record(
        self,
        *,
        correlation_id: str,
        event_type: str,
        actor: str,
        occurred_at: datetime,
        details: Mapping[str, Any] | None = None,
    ) -> AuditEvent:
        if not correlation_id or not event_type or not actor:
            raise ValueError("correlation_id, event_type, and actor are required")
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        normalized_time = occurred_at.astimezone(timezone.utc)
        stream = self._events.setdefault(correlation_id, [])
        event = AuditEvent(
            event_id=uuid7(timestamp_ms=int(normalized_time.timestamp() * 1000)),
            correlation_id=correlation_id,
            sequence=len(stream) + 1,
            event_type=event_type,
            actor=actor,
            occurred_at=normalized_time,
            details=freeze_json(details or {}),
        )
        stream.append(event)
        return event

    def events(self, correlation_id: str) -> tuple[AuditEvent, ...]:
        return tuple(self._events.get(correlation_id, ()))
