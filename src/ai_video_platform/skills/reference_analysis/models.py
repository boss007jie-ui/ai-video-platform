"""Immutable public results for Reference Analysis."""

from __future__ import annotations

from dataclasses import dataclass
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
class AnalysisResult:
    status: str
    output_path: str
    artifact: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", _freeze(self.artifact))

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "output_path": self.output_path, "artifact": _thaw(self.artifact)}


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    status: str
    output_path: str
    artifact: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", _freeze(self.artifact))

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "output_path": self.output_path, "artifact": _thaw(self.artifact)}


@dataclass(frozen=True, slots=True)
class StoryboardAnalysisResult:
    status: str
    output_root: str
    artifact: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", _freeze(self.artifact))

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "output_root": self.output_root, "artifact": _thaw(self.artifact)}


@dataclass(frozen=True, slots=True)
class ReferenceBreakdownDraftResult:
    status: str
    output_root: str
    artifact: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", _freeze(self.artifact))

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "output_root": self.output_root, "artifact": _thaw(self.artifact)}
