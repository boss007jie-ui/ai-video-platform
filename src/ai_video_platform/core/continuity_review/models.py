"""Immutable assembly and consumption records for continuity review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ReferenceImage:
    reference_id: str
    path: Path
    byte_size: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ContinuityReviewAssembly:
    narrative_mode: str
    lead_persona_ids: tuple[str, ...]
    scene_anchor_ids: tuple[str, ...]
    references: tuple[ReferenceImage, ...]

    @property
    def reference_image_paths(self) -> tuple[Path, ...]:
        return tuple(reference.path for reference in self.references)


@dataclass(frozen=True, slots=True)
class ContinuityReviewContext:
    narrative_mode: str
    lead_persona_ids: tuple[str, ...]
    scene_anchor_ids: tuple[str, ...]
    reference_image_paths: tuple[Path, ...]


__all__ = [
    "ContinuityReviewAssembly",
    "ContinuityReviewContext",
    "ReferenceImage",
]
