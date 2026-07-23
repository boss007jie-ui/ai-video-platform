"""Provider-neutral viral script data and validation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, nested in value.items():
        if isinstance(nested, Mapping):
            frozen[str(key)] = _freeze_mapping(nested)
        elif isinstance(nested, (list, tuple)):
            frozen[str(key)] = tuple(
                _freeze_mapping(item) if isinstance(item, Mapping) else item
                for item in nested
            )
        else:
            frozen[str(key)] = nested
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    field_path: str
    message: str


@dataclass(frozen=True, slots=True)
class ViralScriptValidation:
    blockers: tuple[ValidationIssue, ...] = ()
    warnings: tuple[ValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.blockers


@dataclass(frozen=True, slots=True)
class ViralScript:
    script_id: str
    content: str
    submitted_context: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.submitted_context, Mapping):
            object.__setattr__(self, "submitted_context", _freeze_mapping(self.submitted_context))

    def validate(self) -> ViralScriptValidation:
        return validate_viral_script(self)


def validate_viral_script(script: ViralScript) -> ViralScriptValidation:
    """Validate script identity and content without blocking on submitted context."""

    blockers: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    if not isinstance(script.script_id, str) or not script.script_id.strip():
        blockers.append(ValidationIssue("script_id", "script_id must be a non-empty string"))
    if not isinstance(script.content, str) or not script.content.strip():
        blockers.append(ValidationIssue("content", "content must be a non-empty string"))

    submitted_context = script.submitted_context
    if submitted_context is None:
        warnings.append(
            ValidationIssue(
                "submitted_context",
                "submitted_context was not supplied; downstream repair may use product facts",
            )
        )
    elif not isinstance(submitted_context, Mapping):
        warnings.append(
            ValidationIssue(
                "submitted_context",
                "submitted_context should be a mapping; the script remains consumable",
            )
        )
    elif not submitted_context:
        warnings.append(
            ValidationIssue(
                "submitted_context",
                "submitted_context is empty; downstream repair may use product facts",
            )
        )

    return ViralScriptValidation(blockers=tuple(blockers), warnings=tuple(warnings))
