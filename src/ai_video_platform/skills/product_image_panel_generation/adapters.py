"""Internal Provider seam with offline fake and deny-by-default adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

from .errors import ImagePanelError, ImagePanelErrorCode
from .models import CancellationToken, GenerationItem, ModelProfile


def _bypass_error() -> ImagePanelError:
    return ImagePanelError(
        ImagePanelErrorCode.PROVIDER_BYPASS_FORBIDDEN,
        "Provider adapters may only be invoked through the validated orchestration service",
        category="authorization",
    )


@dataclass(frozen=True, slots=True)
class ProviderInvocation:
    request_id: str
    request_hash: str
    item: GenerationItem
    profile: ModelProfile
    compiled_prompt: str
    attempt: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ProviderAsset:
    provider_asset_id: str
    content: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class FakeProviderStep:
    kind: str
    content: bytes = b"synthetic-offline-image"
    content_type: str = "image/png"
    message: str = "Synthetic Provider failure"
    retryable: bool = False
    details: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def success(cls, *, content: bytes = b"synthetic-offline-image", content_type: str = "image/png") -> "FakeProviderStep":
        return cls("success", content=bytes(content), content_type=content_type)

    @classmethod
    def failure(cls, message: str, *, retryable: bool, details: Mapping[str, object] | None = None) -> "FakeProviderStep":
        return cls("failure", message=message, retryable=retryable, details=MappingProxyType(dict(details or {})))

    @classmethod
    def timeout(cls, *, details: Mapping[str, object] | None = None) -> "FakeProviderStep":
        return cls("timeout", message="Synthetic Provider timeout", details=MappingProxyType(dict(details or {})))


class FakeImageProviderAdapter:
    """Deterministic offline adapter with per-item scripted outcomes."""

    provider_id = "offline-fake"

    def __init__(
        self,
        *,
        script: Mapping[str, list[FakeProviderStep]] | None = None,
        before_generate: Callable[[ProviderInvocation], None] | None = None,
    ) -> None:
        self._script = {key: list(steps) for key, steps in (script or {}).items()}
        self._attempts: dict[str, int] = {}
        self._invocations: list[ProviderInvocation] = []
        self._before_generate = before_generate

    @property
    def total_attempts(self) -> int:
        return sum(self._attempts.values())

    def attempts_for(self, item_id: str) -> int:
        return self._attempts.get(item_id, 0)

    @property
    def invocations(self) -> tuple[ProviderInvocation, ...]:
        return tuple(self._invocations)

    def generate(self, *_args, **_kwargs) -> ProviderAsset:
        """Public direct-call surface always rejects; orchestration uses the private seam."""

        raise _bypass_error()

    def _generate(
        self,
        invocation: ProviderInvocation,
        *,
        cancellation: CancellationToken,
    ) -> ProviderAsset:
        if cancellation.cancelled:
            raise ImagePanelError(ImagePanelErrorCode.CANCELLED, "Generation was cancelled", category="state")
        self._invocations.append(invocation)
        self._attempts[invocation.item.item_id] = self.attempts_for(invocation.item.item_id) + 1
        if self._before_generate is not None:
            self._before_generate(invocation)
        if cancellation.cancelled:
            raise ImagePanelError(ImagePanelErrorCode.CANCELLED, "Generation was cancelled", category="state")
        steps = self._script.get(invocation.item.item_id, [])
        step_index = self._attempts[invocation.item.item_id] - 1
        step = steps[step_index] if step_index < len(steps) else FakeProviderStep.success()
        if step.kind == "success":
            return ProviderAsset(
                provider_asset_id=f"fake:{invocation.request_id}:{invocation.item.item_id}:{invocation.attempt}",
                content=bytes(step.content),
                content_type=step.content_type,
            )
        if step.kind == "timeout":
            raise ImagePanelError(
                ImagePanelErrorCode.PROVIDER_TIMEOUT,
                "Provider attempt exceeded the configured timeout",
                category="provider",
                details=step.details,
            )
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_FAILED,
            "Provider attempt failed",
            category="provider",
            retryable=step.retryable,
            details=step.details,
        )


class RejectingImageProviderAdapter:
    """Default adapter for public use until a Provider-specific FTG-P exists."""

    provider_id = "rejecting"

    def generate(self, *_args, **_kwargs):
        raise _bypass_error()

    def _generate(self, *_args, **_kwargs):
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
            "Real image Provider execution is not authorized",
            category="authorization",
        )
