"""Immutable local result models; these are not cross-Skill Contracts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ResearchInspection:
    status: str
    request_digest: str
    expanded_queries: tuple[str, ...]
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "request_digest": self.request_digest,
            "expanded_queries": list(self.expanded_queries),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class ResearchScore:
    total: float
    explanation: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "explanation", MappingProxyType(dict(self.explanation)))

    def to_dict(self) -> dict[str, object]:
        return {"total": self.total, "explanation": dict(self.explanation)}


@dataclass(frozen=True, slots=True)
class ResearchCandidate:
    source_id: str
    source_url: str
    title: str
    content_digest: str
    lifecycle_state: str
    rights_status: str
    pii_detected: bool
    expires_at: str
    score: ResearchScore
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "title": self.title,
            "content_digest": self.content_digest,
            "lifecycle_state": self.lifecycle_state,
            "rights_status": self.rights_status,
            "pii_detected": self.pii_detected,
            "expires_at": self.expires_at,
            "score": self.score.to_dict(),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class ResearchResult:
    status: str
    request_digest: str
    provider_calls: int
    candidates: tuple[ResearchCandidate, ...]
    partial: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "request_digest": self.request_digest,
            "provider_calls": self.provider_calls,
            "partial": self.partial,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True, slots=True)
class CollectionItem:
    source_id: str
    lifecycle_state: str
    rights_status: str
    object_digest: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "lifecycle_state": self.lifecycle_state,
            "rights_status": self.rights_status,
            "object_digest": self.object_digest,
        }


@dataclass(frozen=True, slots=True)
class CollectionResult:
    status: str
    items: tuple[CollectionItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "items": [item.to_dict() for item in self.items]}
