"""Canonical target manifest for the public root CLI.

The manifest is orchestration metadata, not a business implementation.  Every
target remains fail-closed until the owning Skill publishes and tests the
matching public command and Codex-00 wires that command in a later merge.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RootCliTarget:
    namespace: str
    command: str
    owner: str
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    status: str = "TARGET_NOT_ROUTED"


ROOT_CLI_TARGETS = (
    RootCliTarget(
        namespace="viral-research",
        command="search",
        owner="viral-research-asset-collection",
        required_inputs=("ViralResearchRequest",),
        optional_inputs=(),
        outputs=("ViralResearchPack", "ReferenceCollectionManifest"),
    ),
    RootCliTarget(
        namespace="reference-analysis",
        command="analyze-storyboard",
        owner="reference-analysis",
        required_inputs=("selected-reference-video", "video-metadata", "analysis-config"),
        optional_inputs=("ViralResearchPack", "popular-comments"),
        outputs=(
            "ReferenceStoryboardAnalysis",
            "ReferenceBeat",
            "ReferenceShotEvidence",
            "ReplicationPattern",
            "ReferenceAnalysisBoardManifest",
        ),
    ),
    RootCliTarget(
        namespace="storyboard",
        command="derive-production-panels",
        owner="storyboard",
        required_inputs=("TaskSpec", "ProductContextBundle"),
        optional_inputs=(
            "ReferenceStoryboardAnalysis",
            "ReplicationPattern",
            "production-constraints",
        ),
        outputs=("ProductionStoryboardPlan", "ProductionStoryboardPanelPlan"),
    ),
    RootCliTarget(
        namespace="image-panel",
        command="generate-panels",
        owner="product-image-panel-generation",
        required_inputs=(
            "ProductionStoryboardPanelPlan",
            "ProductContextBundle",
            "AnchorSet",
            "approved-assets",
        ),
        optional_inputs=(),
        outputs=("ProductionStoryboardPanelSet",),
    ),
    RootCliTarget(
        namespace="video-planning",
        command="build-storyboard-master",
        owner="storyboard-master-video-planning",
        required_inputs=(
            "ProductionStoryboardPlan",
            "ProductionStoryboardPanelSet",
            "ProductContextBundle",
            "approved-panel-results",
        ),
        optional_inputs=("ReferenceAnalysisBoardManifest",),
        outputs=(
            "VideoGenerationStoryboardMaster",
            "ShotMotionPlan",
            "VideoExecutionPackage",
            "FirstFrameMapping",
            "ReferenceRoleMapping",
        ),
    ),
    RootCliTarget(
        namespace="video-generation",
        command="run",
        owner="video-generation",
        required_inputs=(
            "VideoGenerationStoryboardMaster",
            "ShotMotionPlan",
            "VideoExecutionPackage",
            "FirstFrameMapping",
            "ReferenceRoleMapping",
            "approved-panels-and-reference-assets",
        ),
        optional_inputs=(),
        outputs=("VideoResult",),
    ),
    RootCliTarget(
        namespace="qa-review",
        command="review-artifact",
        owner="qa-review",
        required_inputs=("artifact-ref", "review-criteria"),
        optional_inputs=("ProductContextBundle",),
        outputs=("ReviewDecision",),
    ),
    RootCliTarget(
        namespace="qa-review",
        command="review-composition",
        owner="qa-review",
        required_inputs=("storyboard-artifact-chain", "review-criteria"),
        optional_inputs=("ProductContextBundle",),
        outputs=("ReviewDecision",),
    ),
)


__all__ = ["ROOT_CLI_TARGETS", "RootCliTarget"]
