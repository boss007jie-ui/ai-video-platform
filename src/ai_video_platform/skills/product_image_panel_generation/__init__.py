"""Public interface for safe offline product image and panel generation."""

from .adapters import FakeImageProviderAdapter, FakeProviderStep, RejectingImageProviderAdapter
from .errors import ImagePanelError, ImagePanelErrorCode
from .codec import generation_request_from_mapping, generation_request_to_mapping, model_profile_from_mapping, model_profile_to_mapping
from .models import (
    GenerationBudget,
    CancellationToken,
    GenerationCommand,
    GenerationItem,
    GenerationOutcome,
    GenerationRequest,
    GenerationStatus,
    ModelProfile,
    PreflightInspection,
    calculate_model_profile_digest,
    calculate_request_hash,
)
from .service import ImagePanelService

__all__ = [
    "FakeImageProviderAdapter",
    "FakeProviderStep",
    "CancellationToken",
    "GenerationBudget",
    "GenerationCommand",
    "GenerationItem",
    "GenerationOutcome",
    "GenerationRequest",
    "GenerationStatus",
    "ImagePanelError",
    "ImagePanelErrorCode",
    "ImagePanelService",
    "ModelProfile",
    "PreflightInspection",
    "RejectingImageProviderAdapter",
    "calculate_request_hash",
    "calculate_model_profile_digest",
    "generation_request_from_mapping",
    "generation_request_to_mapping",
    "model_profile_from_mapping",
    "model_profile_to_mapping",
]
