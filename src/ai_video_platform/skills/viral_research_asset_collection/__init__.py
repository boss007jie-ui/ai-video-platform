"""Public offline interface for Viral Research & Asset Collection."""

from .errors import ErrorCode, SkillError
from .interface import collect_reference_assets, inspect_research_request, research_viral
from .models import CollectionResult, ResearchInspection, ResearchResult, ViralResearchPack
from .pack import project_viral_research_pack

__all__ = [
    "CollectionResult",
    "ErrorCode",
    "ResearchInspection",
    "ResearchResult",
    "ViralResearchPack",
    "SkillError",
    "collect_reference_assets",
    "inspect_research_request",
    "project_viral_research_pack",
    "research_viral",
]
