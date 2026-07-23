"""Assembly boundary for continuity-review inputs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .models import ContinuityReviewAssembly, ReferenceImage
from .references import (
    ReferenceSource,
    _image_dimensions,
    load_ref_image_paths_by_ids,
)


def _ids(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{field_name} must contain non-empty strings")
    return result


def assemble_continuity_review(
    *,
    sources: ReferenceSource,
    reference_ids: Iterable[str],
    narrative_mode: str,
    lead_persona_ids: Iterable[str] = (),
    scene_anchor_ids: Iterable[str] = (),
) -> ContinuityReviewAssembly:
    """Resolve and validate local images while preserving continuity fields."""

    if not isinstance(narrative_mode, str) or not narrative_mode.strip():
        raise ValueError("narrative_mode must be a non-empty string")
    requested_ids = _ids(reference_ids, "reference_ids")
    paths = load_ref_image_paths_by_ids(sources, requested_ids)
    references = []
    for reference_id, path in zip(requested_ids, paths, strict=True):
        width, height = _image_dimensions(path, path.read_bytes())
        references.append(
            ReferenceImage(
                reference_id=reference_id,
                path=Path(path),
                byte_size=path.stat().st_size,
                width=width,
                height=height,
            )
        )
    return ContinuityReviewAssembly(
        narrative_mode=narrative_mode,
        lead_persona_ids=_ids(lead_persona_ids, "lead_persona_ids"),
        scene_anchor_ids=_ids(scene_anchor_ids, "scene_anchor_ids"),
        references=tuple(references),
    )


assemble = assemble_continuity_review


__all__ = ["assemble", "assemble_continuity_review"]
