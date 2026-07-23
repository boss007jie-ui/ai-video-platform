# Storyboard Artifact Producer / Consumer Map V1

Authorization: `FTG-0-20260720-001`
Decision type: additive artifact-chain correction
Top-level Skill count: unchanged at eight

## Production chain

```text
ViralResearchPack (optional)
  -> ReferenceStoryboardAnalysis
  -> ProductionStoryboardPlan
  -> ProductionStoryboardPanelPlan
  -> ProductionStoryboardPanelSet
  -> VideoGenerationStoryboardMaster
  -> ShotMotionPlan
  -> VideoExecutionPackage
  -> VideoResult
```

`ProductContextBundle` is a required product-identity input to production planning, panel generation, and video planning. It is not replaced by `TaskContext`.

## Ownership and handoff

| Artifact | Unique producer | Required or principal inputs | Principal consumers |
|---|---|---|---|
| ReferenceStoryboardAnalysis | Reference Analysis | selected reference video; optional ViralResearchPack, metadata, comments | Storyboard; QA / Review |
| ReferenceBeat | Reference Analysis | real reference timeline and evidence | ReferenceStoryboardAnalysis; Storyboard; QA / Review |
| ReferenceShotEvidence | Reference Analysis | real keyframes, time ranges, source provenance | ReferenceStoryboardAnalysis; QA / Review |
| ReplicationPattern | Reference Analysis | reference behavior, reusable mechanism, product-safe transfer | Storyboard; QA / Review |
| ReferenceAnalysisBoardManifest | Reference Analysis | analysis/evidence/replication boards and keyframes | user review; QA / Review; optionally Video Planning as structural context |
| ProductionStoryboardPlan | Storyboard | TaskSpec, ProductContextBundle, optional reference analysis and patterns | Product Image / Panel Generation; Video Planning; QA / Review |
| ProductionStoryboardPanelPlan | Storyboard | ProductionStoryboardPlan, approved assets and production constraints | Product Image / Panel Generation; QA / Review |
| ProductionStoryboardPanelSet | Product Image / Panel Generation | PanelPlan, ProductContextBundle, AnchorSet, approved assets | Video Planning; QA / Review |
| VideoGenerationStoryboardMaster | Storyboard Master / Video Planning | ProductionStoryboardPlan, approved PanelSet, ProductContextBundle | Video Generation; QA / Review |
| ShotMotionPlan | Storyboard Master / Video Planning | VideoGenerationStoryboardMaster and approved panels | Video Generation; QA / Review |
| VideoExecutionPackage | Storyboard Master / Video Planning | master, motion plan, first-frame and reference-role mappings | Video Generation; QA / Review |
| FirstFrameMapping | Storyboard Master / Video Planning | first shot and its approved clean panel | Video Generation; QA / Review |
| ReferenceRoleMapping | Storyboard Master / Video Planning | approved panels and permitted reference assets | Video Generation; QA / Review |

Hermes orchestrates references between producers and consumers but is not a producer of these thirteen artifacts.

## Non-substitution rules

| Artifact class | Meaning | Must never substitute for |
|---|---|---|
| ReferenceStoryboardAnalysisBoard | visualization of another video's evidence and mechanics | ProductionStoryboardPanelSet; FirstFrameMapping; provider execution input |
| ProductionStoryboardPanelSet | approved real panels for the current product | reference evidence; final execution master |
| VideoGenerationStoryboardMaster | final ordered video execution blueprint | source evidence board; contact sheet |

A `ReferenceAnalysisBoardManifest` may reach Video Planning only when `ReferenceRoleMapping` labels it `global_structure_reference`. That role always has `provider_execution_input=false` and `first_frame_eligible=false`.

The first frame must resolve to one clean full-frame panel from `ProductionStoryboardPanelSet`, match the video aspect ratio, and contain no grid, numbering, labels, or overlaid text. `storyboard_contact_sheet`, analysis boards, evidence boards, and replication boards are categorically ineligible.

## Directory ownership

| Producer | Output root |
|---|---|
| Reference Analysis | `reference_analysis/` |
| Storyboard | `production_storyboard_plan/` |
| Product Image / Panel Generation | `production_storyboard_panels/` |
| Storyboard Master / Video Planning | `video_generation_storyboard/` |

Binary files remain assets referenced by a canonical manifest or contract. File names are not Contract identities.
