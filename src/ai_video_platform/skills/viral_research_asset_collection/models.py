"""Immutable local result models; these are not cross-Skill Contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


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
    inputs: Mapping[str, float]
    weights: Mapping[str, float]
    contributions: Mapping[str, float]
    explanation: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))
        object.__setattr__(self, "contributions", MappingProxyType(dict(self.contributions)))
        object.__setattr__(self, "explanation", MappingProxyType(dict(self.explanation)))

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "inputs": dict(self.inputs),
            "weights": dict(self.weights),
            "contributions": dict(self.contributions),
            "explanation": dict(self.explanation),
        }


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
    source_metadata: Mapping[str, object] = field(default_factory=dict)
    comment_evidence: Mapping[str, object] = field(default_factory=dict)
    source_provenance: Mapping[str, object] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_metadata", _freeze(self.source_metadata))
        object.__setattr__(self, "comment_evidence", _freeze(self.comment_evidence))
        object.__setattr__(self, "source_provenance", _freeze(self.source_provenance))

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
            "source_metadata": _thaw(self.source_metadata),
            "comment_evidence": _thaw(self.comment_evidence),
            "source_provenance": _thaw(self.source_provenance),
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
class ViralResearchPack:
    artifact: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", _freeze(self.artifact))

    def to_dict(self) -> dict[str, object]:
        return _thaw(self.artifact)


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
