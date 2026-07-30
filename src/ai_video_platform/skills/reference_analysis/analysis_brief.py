"""Human intent contract for Reference Analysis.

The execution Agent gathers this small brief before invoking the deterministic
Reference Analysis implementation.  Technical replication profiles are derived
here so callers cannot silently choose a default that conflicts with the stated
analysis focus.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .errors import ErrorCode, SkillError


ANALYSIS_OBJECTIVES = frozenset({
    "MECHANISM_EXTRACTION",
    "REPLICATION_REFERENCE",
    "STORYBOARD_TRANSFER",
    "RESULT_COMPARISON",
})
ANALYSIS_FOCUSES = frozenset({
    "EDITING_RHYTHM",
    "MOTION",
    "NARRATIVE",
    "PRODUCT_PROOF",
    "SCENE_BLOCKING",
    "AUDIO_VISUAL",
})
ANALYSIS_DEPTHS = frozenset({"OVERVIEW", "DETAILED"})
HYPOTHESIS_POLICIES = frozenset({"OBSERVED_ONLY", "LABEL_UNVERIFIED"})
REPLICATION_TARGETS = frozenset({
    "MOTION_1_TO_1",
    "NARRATIVE_1_TO_1",
    "HYBRID_1_TO_1",
    "QUICK_OVERVIEW",
})
INFERENCE_CHOICES = frozenset({"FACTS_ONLY", "LABELED_HYPOTHESES"})
_BRIEF_KEYS = {"objective", "focus", "depth", "hypothesis_policy"}
_TARGET_BRIEFS: dict[str, dict[str, object]] = {
    "MOTION_1_TO_1": {
        "objective": "REPLICATION_REFERENCE",
        "focus": ["MOTION", "SCENE_BLOCKING"],
        "depth": "DETAILED",
    },
    "NARRATIVE_1_TO_1": {
        "objective": "REPLICATION_REFERENCE",
        "focus": ["NARRATIVE", "EDITING_RHYTHM", "AUDIO_VISUAL"],
        "depth": "DETAILED",
    },
    "HYBRID_1_TO_1": {
        "objective": "REPLICATION_REFERENCE",
        "focus": [
            "MOTION",
            "NARRATIVE",
            "PRODUCT_PROOF",
            "SCENE_BLOCKING",
            "EDITING_RHYTHM",
            "AUDIO_VISUAL",
        ],
        "depth": "DETAILED",
    },
    "QUICK_OVERVIEW": {
        "objective": "MECHANISM_EXTRACTION",
        "focus": ["EDITING_RHYTHM", "AUDIO_VISUAL"],
        "depth": "OVERVIEW",
    },
}


def _validate_enum_value(value: object, allowed: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            f"{field} is missing or unsupported",
            field_paths=(field,),
        )
    return value


def validate_analysis_brief(value: object, *, field: str = "analysis_brief") -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "An explicit analysis brief is required before Reference Analysis",
            field_paths=(field,),
        )
    unexpected = sorted(set(value) - _BRIEF_KEYS)
    missing = sorted(_BRIEF_KEYS - set(value))
    if unexpected or missing:
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "Analysis brief fields do not match the versioned interface",
            field_paths=tuple(
                [*(f"{field}.{name}" for name in missing), *(f"{field}.{name}" for name in unexpected)]
            ),
        )
    raw_focus = value.get("focus")
    if (
        not isinstance(raw_focus, Sequence)
        or isinstance(raw_focus, (str, bytes, bytearray))
        or not raw_focus
    ):
        raise SkillError(
            ErrorCode.VALIDATION_FAILED,
            "analysis_brief.focus must be a non-empty array",
            field_paths=(f"{field}.focus",),
        )
    focus: list[str] = []
    for index, item in enumerate(raw_focus):
        normalized = _validate_enum_value(item, ANALYSIS_FOCUSES, f"{field}.focus[{index}]")
        if normalized in focus:
            raise SkillError(
                ErrorCode.VALIDATION_FAILED,
                "analysis_brief.focus cannot contain duplicates",
                field_paths=(f"{field}.focus[{index}]",),
            )
        focus.append(normalized)
    return {
        "objective": _validate_enum_value(
            value.get("objective"), ANALYSIS_OBJECTIVES, f"{field}.objective"
        ),
        "focus": focus,
        "depth": _validate_enum_value(value.get("depth"), ANALYSIS_DEPTHS, f"{field}.depth"),
        "hypothesis_policy": _validate_enum_value(
            value.get("hypothesis_policy"), HYPOTHESIS_POLICIES, f"{field}.hypothesis_policy"
        ),
    }


def derive_analysis_profile(brief: Mapping[str, object]) -> str:
    focus = set(brief["focus"])  # type: ignore[arg-type]
    motion = bool(focus & {"MOTION", "SCENE_BLOCKING", "PRODUCT_PROOF"})
    narrative = bool(focus & {"NARRATIVE", "PRODUCT_PROOF", "EDITING_RHYTHM", "AUDIO_VISUAL"})
    if motion and narrative:
        return "HYBRID_REPLICATION"
    if motion:
        return "MOTION_REPLICATION"
    return "NARRATIVE_REPLICATION"


def build_analysis_brief_from_choices(
    replication_target: object,
    inference_choice: object,
) -> dict[str, object]:
    """Map the two user-facing questions to the internal Analysis Brief."""
    target = _validate_enum_value(
        replication_target,
        REPLICATION_TARGETS,
        "replication_target",
    )
    inference = _validate_enum_value(
        inference_choice,
        INFERENCE_CHOICES,
        "inference_choice",
    )
    return validate_analysis_brief({
        **_TARGET_BRIEFS[target],
        "hypothesis_policy": (
            "OBSERVED_ONLY" if inference == "FACTS_ONLY" else "LABEL_UNVERIFIED"
        ),
    })


def requires_replication_package(brief: Mapping[str, object]) -> bool:
    """Return whether the requested intent needs fine, coverage-complete evidence."""
    focus = set(brief["focus"])  # type: ignore[arg-type]
    return (
        brief["depth"] == "DETAILED"
        or brief["objective"] != "MECHANISM_EXTRACTION"
        or bool(focus & {"MOTION", "NARRATIVE", "PRODUCT_PROOF", "SCENE_BLOCKING"})
    )
