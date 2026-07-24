"""Immutable public models for the clean-room QA / Review Skill."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .errors import QAError, QAErrorCode



class ReviewOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs-review"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    schema_version: str
    criteria_version: str
    evaluation_set_version: str
    command: str
    task_id: str
    execution_id: str
    subject: Mapping[str, Any]
    criteria: Mapping[str, Any]
    context: Mapping[str, Any]
    evidence_refs: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReviewRequest":
        if not isinstance(value, Mapping):
            raise QAError(QAErrorCode.QA_INPUT_INVALID, "validation", "QA request must be an object")
        required = (
            "schema_version", "criteria_version", "evaluation_set_version", "command",
            "task_id", "execution_id", "subject", "criteria", "context", "evidence_refs",
        )
        missing = [name for name in required if name not in value]
        if missing:
            raise QAError(
                QAErrorCode.QA_INPUT_INVALID,
                "validation",
                "QA request is missing required fields",
                field_paths=tuple(missing),
            )
        schema_version = str(value["schema_version"])
        try:
            major = int(schema_version.split(".", 1)[0])
        except (ValueError, IndexError) as exc:
            raise QAError(
                QAErrorCode.QA_SCHEMA_UNSUPPORTED,
                "compatibility",
                "QA request schema_version must be SemVer",
                field_paths=("schema_version",),
            ) from exc
        if major != 1:
            raise QAError(
                QAErrorCode.QA_SCHEMA_UNSUPPORTED,
                "compatibility",
                "QA request schema major version is unsupported",
                field_paths=("schema_version",),
            )
        command = str(value["command"])
        supported_commands = {
            "review-asset", "review-storyboard", "review-video-plan", "review-video-result",
            "review-artifact", "review-composition",
        }
        if command not in supported_commands:
            raise QAError(
                QAErrorCode.QA_COMMAND_UNSUPPORTED,
                "validation",
                "QA review command is unsupported",
                field_paths=("command",),
            )
        for field_name in ("subject", "criteria", "context"):
            if not isinstance(value[field_name], Mapping):
                raise QAError(
                    QAErrorCode.QA_INPUT_INVALID,
                    "validation",
                    f"{field_name} must be an object",
                    field_paths=(field_name,),
                )
        evidence_refs = value["evidence_refs"]
        if not isinstance(evidence_refs, Sequence) or isinstance(evidence_refs, (str, bytes, bytearray)):
            raise QAError(
                QAErrorCode.QA_INPUT_INVALID,
                "validation",
                "evidence_refs must be an array",
                field_paths=("evidence_refs",),
            )
        forbidden = {
            "semantic_reference_comparison", "compare_result", "reference_blueprint_gap",
        }.intersection(value["criteria"])
        if forbidden:
            raise QAError(
                QAErrorCode.QA_CRITERION_FORBIDDEN,
                "authorization",
                "Reference Analysis semantic comparison is outside QA ownership",
                field_paths=tuple(f"criteria.{name}" for name in sorted(forbidden)),
            )
        return cls(
            schema_version=schema_version,
            criteria_version=str(value["criteria_version"]),
            evaluation_set_version=str(value["evaluation_set_version"]),
            command=command,
            task_id=str(value["task_id"]),
            execution_id=str(value["execution_id"]),
            subject=_freeze(value["subject"]),
            criteria=_freeze(value["criteria"]),
            context=_freeze(value["context"]),
            evidence_refs=tuple(str(item) for item in evidence_refs),
        )


@dataclass(frozen=True, slots=True)
class ReviewArtifacts:
    outcome: ReviewOutcome
    review_decision: Mapping[str, Any]
    feedback_events: tuple[Mapping[str, Any], ...]
    human_review_package: Mapping[str, Any]
    skill_execution_event: Mapping[str, Any]
