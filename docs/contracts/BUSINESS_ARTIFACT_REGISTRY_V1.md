# Fast Track Business Artifact Registry V1

Authorization: `FTG-0-20260720-001`  
Registry version: `1.0.0`

This registry is separate from the immutable Foundation Registry. The Foundation Registry remains one Envelope schema identity and eleven payload Contract IDs. Registration here fixes a cross-Skill business identity, producer, consumer set, and compatibility version; it does not make that identity a valid `ContractEnvelope.contract_type` until its schema and validator are published at the applicable contract gate.

## Registered artifacts

| Artifact | Identity | Sole owner / producer | Authorized consumers | Version |
|---|---|---|---|---|
| ViralResearchRequest | `avp.contract.viral-research-request` | Viral Research intake boundary; Hermes or authorized direct caller may produce | Viral Research & Asset Collection | `1.0.0` |
| ViralResearchPack | `avp.contract.viral-research-pack` | Viral Research & Asset Collection | Hermes, user review, Reference Analysis, QA / Review | `1.0.0` |
| ReferenceCollectionManifest | `avp.contract.reference-collection-manifest` | Viral Research & Asset Collection | Reference Analysis, Hermes, QA / Review | `1.0.0` |
| ReferenceStoryboardAnalysis | `avp.contract.reference-storyboard-analysis` | Reference Analysis | Storyboard, QA / Review, Hermes, user review | `1.0.0` |
| ReferenceBeat | `avp.contract.reference-beat` | Reference Analysis | Reference Analysis, Storyboard, QA / Review, Hermes | `1.0.0` |
| ReferenceShotEvidence | `avp.contract.reference-shot-evidence` | Reference Analysis | Reference Analysis, Storyboard, QA / Review, Hermes, user review | `1.0.0` |
| ReplicationPattern | `avp.contract.replication-pattern` | Reference Analysis | Storyboard, QA / Review, Hermes, user review | `1.0.0` |
| ReferenceAnalysisBoardManifest | `avp.contract.reference-analysis-board-manifest` | Reference Analysis | Storyboard, Video Planning, QA / Review, Hermes, user review | `1.0.0` |
| ProductionStoryboardPlan | `avp.contract.production-storyboard-plan` | Storyboard | Product Image / Panel Generation, Video Planning, QA / Review, Hermes | `1.0.0` |
| ProductionStoryboardPanelPlan | `avp.contract.production-storyboard-panel-plan` | Storyboard | Product Image / Panel Generation, QA / Review, Hermes | `1.0.0` |
| ProductionStoryboardPanelSet | `avp.contract.production-storyboard-panel-set` | Product Image / Panel Generation | Video Planning, QA / Review, Hermes, user review | `1.0.0` |
| VideoGenerationStoryboardMaster | `avp.contract.video-generation-storyboard-master` | Storyboard Master / Video Planning | Video Generation, QA / Review, Hermes, user review | `1.0.0` |
| ShotMotionPlan | `avp.contract.shot-motion-plan` | Storyboard Master / Video Planning | Video Generation, QA / Review, Hermes | `1.0.0` |
| VideoExecutionPackage | `avp.contract.video-execution-package` | Storyboard Master / Video Planning | Video Generation, QA / Review, Hermes | `1.0.0` |
| FirstFrameMapping | `avp.contract.first-frame-mapping` | Storyboard Master / Video Planning | Video Generation, QA / Review, Hermes | `1.0.0` |
| ReferenceRoleMapping | `avp.contract.reference-role-mapping` | Storyboard Master / Video Planning | Video Generation, QA / Review, Hermes | `1.0.0` |

## Identity decisions

- `VideoGenerationStoryboardMaster` is the canonical cross-Skill identity. The owner-local `StoryboardMaster` `0.1.0 / DRAFT_UNREGISTERED` shape must migrate to it; `StoryboardMaster` is not an alias and is not registered.
- The owner-local `VideoExecutionPackage` `0.1.0 / DRAFT_UNREGISTERED` shape must migrate to the registered `1.0.0` identity before cross-Skill publication.
- `StoryboardArtifact`, `AnalysisResult`, and `GenerationOutcome` remain internal DTO names and must not be published as cross-Skill Contract identities.
- Nested `motion_plan` and `asset_mapping` fields do not satisfy the independent `ShotMotionPlan`, `FirstFrameMapping`, or `ReferenceRoleMapping` contracts.
- `ReferenceStoryboardAnalysisBoard`, `ShotEvidenceBoard`, `ReplicationBoard`, and `storyboard_contact_sheet` are binary artifacts represented through manifests or asset references; none is a video first frame.
- `ViralResearchPack` was already registered and remains unchanged. `VideoResult` remains the Video Generation-owned terminal result named by the production chain; it was not included in the thirteen new Contract identities authorized by this changeset.

## Compatibility

Compatibility follows the Shared Contracts reader/writer SemVer matrix. Same-major readers accept writer versions up to their supported minor; newer-writer minor versions return `reader_too_old`; different majors return `major_mismatch`.

Consumers may use registry metadata for capability negotiation, but must use versioned synthetic fixtures until the corresponding schemas, validators, and permission fixtures are published. No owner-local draft becomes cross-Skill valid merely because the canonical identity is now registered.
