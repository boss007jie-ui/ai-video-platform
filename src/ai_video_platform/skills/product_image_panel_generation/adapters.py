"""Internal Provider seam with offline fake and deny-by-default adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
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
    width: int | None = None
    height: int | None = None
    provider_metadata: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


class ImageProviderAdapter(ABC):
    """Provider-independent seam; direct public calls always fail closed.

    ``_generate`` is an internal implementation convention enforced by the
    repository architecture test, not a security or authorization boundary.
    """

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "generate" in cls.__dict__:
            raise TypeError("Image Provider adapters cannot override fail-closed generate()")

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Stable adapter identifier used to match an approved model profile."""

    def generate(self, *_args, **_kwargs) -> ProviderAsset:
        """Reject direct calls; orchestration owns validation and accounting."""

        raise _bypass_error()

    @abstractmethod
    def _generate(
        self,
        invocation: ProviderInvocation,
        *,
        cancellation: CancellationToken,
    ) -> ProviderAsset:
        """Implement one Provider attempt behind the service-owned seam."""


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


class FakeImageProviderAdapter(ImageProviderAdapter):
    """Deterministic offline adapter with per-item scripted outcomes."""

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

    @property
    def provider_id(self) -> str:
        return "offline-fake"

    def attempts_for(self, item_id: str) -> int:
        return self._attempts.get(item_id, 0)

    @property
    def invocations(self) -> tuple[ProviderInvocation, ...]:
        return tuple(self._invocations)

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


class RejectingImageProviderAdapter(ImageProviderAdapter):
    """Default adapter for public use until a Provider-specific FTG-P exists."""

    @property
    def provider_id(self) -> str:
        return "rejecting"

    def _generate(self, *_args, **_kwargs) -> ProviderAsset:
        raise ImagePanelError(
            ImagePanelErrorCode.PROVIDER_NOT_AUTHORIZED,
            "Real image Provider execution is not authorized",
            category="authorization",
        )
