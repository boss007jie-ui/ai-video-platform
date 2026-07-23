"""Public interface for the clean-room Storyboard Skill."""

from .interface import (
    StoryboardArtifact,
    StoryboardError,
    StoryboardRequest,
    StoryboardResult,
    StoryboardService,
)
from .planning import (
    MAX_PLANNED_PANELS,
    MIN_PLANNED_PANELS,
    build_storyboard_plan,
    decompose_raw_script,
    plan_shots_and_panels,
    validate_continuity_archive,
)

__all__ = [
    "StoryboardArtifact",
    "StoryboardError",
    "StoryboardRequest",
    "StoryboardResult",
    "StoryboardService",
    "MAX_PLANNED_PANELS",
    "MIN_PLANNED_PANELS",
    "build_storyboard_plan",
    "decompose_raw_script",
    "plan_shots_and_panels",
    "validate_continuity_archive",
]
