"""Versioned registry for Fast Track-approved business artifact identities.

Business artifacts are intentionally kept outside the immutable Foundation
Registry.  They are cross-Skill identities, but they are not valid payload
types for ``ContractEnvelope`` until their individual schemas are published.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from .compatibility import Compatibility, SemVer, evaluate_compatibility
from .registry import ENVELOPE_SCHEMA_ID, FOUNDATION_CONTRACT_IDS


BUSINESS_REGISTRY_NAME = "Fast Track Business Artifact Registry V1"
BUSINESS_REGISTRY_VERSION = "1.0.0"
BUSINESS_REGISTRY_AUTHORIZATION = "FTG-0-20260720-001"


@dataclass(frozen=True, slots=True)
class BusinessArtifactDefinition:
    name: str
    artifact_type: str
    version: str
    owner: str
    authorized_producers: tuple[str, ...]
    authorized_consumers: tuple[str, ...]
    deprecated: bool = False
    replacement_artifact_type: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.owner:
            raise ValueError("Business artifact name and owner are required")
        if not self.artifact_type.startswith("avp.contract."):
            raise ValueError("Business artifact identity must use the avp.contract namespace")
        SemVer.parse(self.version)
        if not self.authorized_producers or not self.authorized_consumers:
            raise ValueError("Business artifact producers and consumers are required")
        if self.deprecated and self.replacement_artifact_type == self.artifact_type:
            raise ValueError("A deprecated artifact cannot replace itself")


def build_business_registry(
    definitions: Iterable[BusinessArtifactDefinition],
) -> Mapping[str, BusinessArtifactDefinition]:
    registry: dict[str, BusinessArtifactDefinition] = {}
    foundation_identities = {ENVELOPE_SCHEMA_ID, *FOUNDATION_CONTRACT_IDS}
    for definition in definitions:
        if definition.artifact_type in foundation_identities:
            raise ValueError(
                f"Business artifact identity collides with Foundation Registry: {definition.artifact_type}"
            )
        if definition.artifact_type in registry:
            raise ValueError(f"Duplicate business artifact identity: {definition.artifact_type}")
        registry[definition.artifact_type] = definition
    return MappingProxyType(registry)


_DEFINITIONS = (
    BusinessArtifactDefinition(
        name="ViralResearchRequest",
        artifact_type="avp.contract.viral-research-request",
        version="1.0.0",
        owner="viral-research-asset-collection",
        authorized_producers=("hermes", "authorized-direct-cli-caller"),
        authorized_consumers=("viral-research-asset-collection",),
    ),
    BusinessArtifactDefinition(
        name="ViralResearchPack",
        artifact_type="avp.contract.viral-research-pack",
        version="1.0.0",
        owner="viral-research-asset-collection",
        authorized_producers=("viral-research-asset-collection",),
        authorized_consumers=("hermes", "user-review", "reference-analysis", "qa-review"),
    ),
    BusinessArtifactDefinition(
        name="ReferenceCollectionManifest",
        artifact_type="avp.contract.reference-collection-manifest",
        version="1.0.0",
        owner="viral-research-asset-collection",
        authorized_producers=("viral-research-asset-collection",),
        authorized_consumers=("reference-analysis", "hermes", "qa-review"),
    ),
    BusinessArtifactDefinition(
        name="ReferenceStoryboardAnalysis",
        artifact_type="avp.contract.reference-storyboard-analysis",
        version="1.0.0",
        owner="reference-analysis",
        authorized_producers=("reference-analysis",),
        authorized_consumers=("storyboard", "qa-review", "hermes", "user-review"),
    ),
    BusinessArtifactDefinition(
        name="ReferenceBeat",
        artifact_type="avp.contract.reference-beat",
        version="1.0.0",
        owner="reference-analysis",
        authorized_producers=("reference-analysis",),
        authorized_consumers=("reference-analysis", "storyboard", "qa-review", "hermes"),
    ),
    BusinessArtifactDefinition(
        name="ReferenceShotEvidence",
        artifact_type="avp.contract.reference-shot-evidence",
        version="1.0.0",
        owner="reference-analysis",
        authorized_producers=("reference-analysis",),
        authorized_consumers=(
            "reference-analysis",
            "storyboard",
            "qa-review",
            "hermes",
            "user-review",
        ),
    ),
    BusinessArtifactDefinition(
        name="ReplicationPattern",
        artifact_type="avp.contract.replication-pattern",
        version="1.0.0",
        owner="reference-analysis",
        authorized_producers=("reference-analysis",),
        authorized_consumers=("storyboard", "qa-review", "hermes", "user-review"),
    ),
    BusinessArtifactDefinition(
        name="ReferenceAnalysisBoardManifest",
        artifact_type="avp.contract.reference-analysis-board-manifest",
        version="1.0.0",
        owner="reference-analysis",
        authorized_producers=("reference-analysis",),
        authorized_consumers=(
            "storyboard",
            "storyboard-master-video-planning",
            "qa-review",
            "hermes",
            "user-review",
        ),
    ),
    BusinessArtifactDefinition(
        name="ProductionStoryboardPlan",
        artifact_type="avp.contract.production-storyboard-plan",
        version="1.0.0",
        owner="storyboard",
        authorized_producers=("storyboard",),
        authorized_consumers=(
            "product-image-panel-generation",
            "storyboard-master-video-planning",
            "qa-review",
            "hermes",
        ),
    ),
    BusinessArtifactDefinition(
        name="ProductionStoryboardPanelPlan",
        artifact_type="avp.contract.production-storyboard-panel-plan",
        version="1.0.0",
        owner="storyboard",
        authorized_producers=("storyboard",),
        authorized_consumers=("product-image-panel-generation", "qa-review", "hermes"),
    ),
    BusinessArtifactDefinition(
        name="ProductionStoryboardPanelSet",
        artifact_type="avp.contract.production-storyboard-panel-set",
        version="1.0.0",
        owner="product-image-panel-generation",
        authorized_producers=("product-image-panel-generation",),
        authorized_consumers=(
            "storyboard-master-video-planning",
            "qa-review",
            "hermes",
            "user-review",
        ),
    ),
    BusinessArtifactDefinition(
        name="VideoGenerationStoryboardMaster",
        artifact_type="avp.contract.video-generation-storyboard-master",
        version="1.0.0",
        owner="storyboard-master-video-planning",
        authorized_producers=("storyboard-master-video-planning",),
        authorized_consumers=("video-generation", "qa-review", "hermes", "user-review"),
    ),
    BusinessArtifactDefinition(
        name="ShotMotionPlan",
        artifact_type="avp.contract.shot-motion-plan",
        version="1.0.0",
        owner="storyboard-master-video-planning",
        authorized_producers=("storyboard-master-video-planning",),
        authorized_consumers=("video-generation", "qa-review", "hermes"),
    ),
    BusinessArtifactDefinition(
        name="VideoExecutionPackage",
        artifact_type="avp.contract.video-execution-package",
        version="1.0.0",
        owner="storyboard-master-video-planning",
        authorized_producers=("storyboard-master-video-planning",),
        authorized_consumers=("video-generation", "qa-review", "hermes"),
    ),
    BusinessArtifactDefinition(
        name="FirstFrameMapping",
        artifact_type="avp.contract.first-frame-mapping",
        version="1.0.0",
        owner="storyboard-master-video-planning",
        authorized_producers=("storyboard-master-video-planning",),
        authorized_consumers=("video-generation", "qa-review", "hermes"),
    ),
    BusinessArtifactDefinition(
        name="ReferenceRoleMapping",
        artifact_type="avp.contract.reference-role-mapping",
        version="1.0.0",
        owner="storyboard-master-video-planning",
        authorized_producers=("storyboard-master-video-planning",),
        authorized_consumers=("video-generation", "qa-review", "hermes"),
    ),
)

BUSINESS_REGISTRY = build_business_registry(_DEFINITIONS)
BUSINESS_ARTIFACT_IDS = tuple(BUSINESS_REGISTRY)


def get_business_artifact_definition(artifact_type: str) -> BusinessArtifactDefinition:
    try:
        return BUSINESS_REGISTRY[artifact_type]
    except KeyError as exc:
        raise KeyError(f"Unregistered business artifact identity: {artifact_type}") from exc


def evaluate_business_compatibility(
    artifact_type: str,
    *,
    reader_version: str,
    writer_version: str,
) -> Compatibility:
    definition = get_business_artifact_definition(artifact_type)
    registered = SemVer.parse(definition.version)
    writer = SemVer.parse(writer_version)
    if writer.major != registered.major:
        return Compatibility.MAJOR_MISMATCH
    return evaluate_compatibility(reader_version, writer_version)
