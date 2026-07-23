"""Consumption boundary for assembled continuity-review inputs."""

from __future__ import annotations

from .models import ContinuityReviewAssembly, ContinuityReviewContext


def consume_continuity_review(
    assembly: ContinuityReviewAssembly,
) -> ContinuityReviewContext:
    """Expose only validated immutable fields to the downstream consumer."""

    return ContinuityReviewContext(
        narrative_mode=assembly.narrative_mode,
        lead_persona_ids=assembly.lead_persona_ids,
        scene_anchor_ids=assembly.scene_anchor_ids,
        reference_image_paths=assembly.reference_image_paths,
    )


consume = consume_continuity_review


__all__ = ["consume", "consume_continuity_review"]
