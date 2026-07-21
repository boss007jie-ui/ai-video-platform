"""Small deterministic external Interface for QA / Review."""

from __future__ import annotations

from .engine import review as _review
from .models import ReviewArtifacts, ReviewRequest


SKILL_ID = "qa-review"
SKILL_VERSION = "1.0.0"


def review(request: ReviewRequest) -> ReviewArtifacts:
    return _review(request)
