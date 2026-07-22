"""Public deterministic Reference Analysis interfaces."""

from .errors import ErrorCode, SkillError
from .interface import analyze_reference, compare_result
from .models import AnalysisResult, ComparisonResult

__all__ = [
    "AnalysisResult",
    "ComparisonResult",
    "ErrorCode",
    "SkillError",
    "analyze_reference",
    "compare_result",
]
