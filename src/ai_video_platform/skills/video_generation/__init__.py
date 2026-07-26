"""Public offline Video Generation interface."""

from .errors import GenerationError, GenerationErrorCode
from .interface import VideoGenerationInterface
from .adapters import FakeVideoProviderAdapter, NetworkBlockedVideoProviderAdapter, RejectingVideoProviderAdapter
from .kie_adapter import KieCredentialResolver, KieReferenceImageUploader, KieVideoProviderAdapter
from .ledger import InMemoryVideoExecutionLedger
from .seedance_nz_adapter import (
    FakeSeedanceNzVideoProviderAdapter,
    SeedanceNzCredentialResolver,
    SeedanceNzVideoProviderAdapter,
)

__all__ = [
    "FakeVideoProviderAdapter",
    "FakeSeedanceNzVideoProviderAdapter",
    "GenerationError",
    "GenerationErrorCode",
    "InMemoryVideoExecutionLedger",
    "KieCredentialResolver",
    "KieReferenceImageUploader",
    "KieVideoProviderAdapter",
    "NetworkBlockedVideoProviderAdapter",
    "RejectingVideoProviderAdapter",
    "SeedanceNzCredentialResolver",
    "SeedanceNzVideoProviderAdapter",
    "VideoGenerationInterface",
]
