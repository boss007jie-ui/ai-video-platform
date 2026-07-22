"""Public offline interface for Viral Research & Asset Collection."""

from .errors import ErrorCode, SkillError
from .interface import collect_reference_assets, inspect_research_request, research_viral
from .models import CollectionResult, ResearchInspection, ResearchResult

__all__ = [
    "CollectionResult",
    "ErrorCode",
    "ResearchInspection",
    "ResearchResult",
    "SkillError",
    "collect_reference_assets",
    "inspect_research_request",
    "research_viral",
]
