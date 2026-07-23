"""Provider-neutral continuity-review assembly and consumption seam."""

from .assembly import assemble, assemble_continuity_review
from .consume import consume, consume_continuity_review
from .models import ContinuityReviewAssembly, ContinuityReviewContext, ReferenceImage
from .references import (
    IMAGE_MAX_BYTES,
    IMAGE_MAX_EDGE,
    ReferenceImageError,
    load_ref_image_paths_by_ids,
)

__all__ = [
    "IMAGE_MAX_BYTES",
    "IMAGE_MAX_EDGE",
    "ContinuityReviewAssembly",
    "ContinuityReviewContext",
    "ReferenceImage",
    "ReferenceImageError",
    "assemble",
    "assemble_continuity_review",
    "consume",
    "consume_continuity_review",
    "load_ref_image_paths_by_ids",
]
