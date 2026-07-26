"""Public interface for safe offline product image and panel generation."""

from .adapters import FakeImageProviderAdapter, FakeProviderStep, ImageProviderAdapter, RejectingImageProviderAdapter
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
from .product_data import (
    ChannelProfile,
    ProductFacts,
    derive_product_mode,
    repair_story_context,
    to_product_facts,
)
from .service import ImagePanelService
from .seedance_nz_image_adapter import FakeSeedanceNzImageAdapter, SeedanceNzImageAdapter
from .storyboard_panels import (
    ProductionStoryboardPanelService,
    StoryboardPanelRequest,
    storyboard_panel_request_from_mapping,
)

__all__ = [
    "FakeImageProviderAdapter",
    "FakeProviderStep",
    "FakeSeedanceNzImageAdapter",
    "CancellationToken",
    "ChannelProfile",
    "GenerationBudget",
    "GenerationCommand",
    "GenerationItem",
    "GenerationOutcome",
    "GenerationRequest",
    "GenerationStatus",
    "ImagePanelError",
    "ImagePanelErrorCode",
    "ImagePanelService",
    "ImageProviderAdapter",
    "ModelProfile",
    "PreflightInspection",
    "ProductFacts",
    "ProductionStoryboardPanelService",
    "RejectingImageProviderAdapter",
    "SeedanceNzImageAdapter",
    "StoryboardPanelRequest",
    "calculate_request_hash",
    "calculate_model_profile_digest",
    "derive_product_mode",
    "generation_request_from_mapping",
    "generation_request_to_mapping",
    "model_profile_from_mapping",
    "model_profile_to_mapping",
    "repair_story_context",
    "storyboard_panel_request_from_mapping",
    "to_product_facts",
]
