# Storyboard Artifact Chain V1 Design

Date: 2026-07-24

Status: APPROVED

Target branch: `ft/codex-00-integration`

## Purpose

Complete the production storyboard chain so structured JSON is the sole semantic authority, independently generated production panels are the sole visual inputs, and one or more horizontal storyboard sheets are deterministic read-only renderings of an approved video-generation master.

The production flow is:

```text
structured ProductionStoryboardPlan / ProductionStoryboardPanelPlan
  -> independent ProductionStoryboardPanelSet assets
  -> validated VideoGenerationStoryboardMaster projection
  -> programmatically rendered horizontal PNG sheets
  -> independent fail-closed QA
```

An image model must never freely generate a storyboard sheet or `VideoGenerationStoryboardMaster`. No implementation in this increment may call a real image or video Provider.

## Frozen Subcontracts

This design freezes these owner-local semantic specifications without changing the existing Business Artifact Registry identities or versions:

- `STRUCTURED_STORYBOARD_PLAN_CONTRACT_V1`
- `VIDEO_GENERATION_STORYBOARD_MASTER_RENDERING_CONTRACT_V1`
- `STORYBOARD_ARTIFACT_CHAIN_FAIL_CLOSED_QA_V1`

The existing canonical registered artifacts remain unchanged, including `ProductionStoryboardPlan`, `ProductionStoryboardPanelPlan`, `ProductionStoryboardPanelSet`, and `VideoGenerationStoryboardMaster` at `1.0.0`.

## Ownership

The chain preserves current producer boundaries:

| Owner | Responsibility |
|---|---|
| Storyboard | Validate and publish the structured plan and panel plan. |
| Product Image / Panel Generation | Generate and describe independent production panel assets. |
| Storyboard Master / Video Planning | Validate execution bindings, publish the execution projection, mappings, and programmatic sheets. |
| QA / Review | Independently validate immutable owner artifacts and publish only QA reports. |

No owner may infer semantic fields from a sheet, OCR a sheet, or rewrite another owner's artifact.

## Structured Storyboard Plan

### Workflow profile

Shot-count limits belong to an explicit workflow profile, not the platform-wide artifact identity. The `short_form` workflow profile requires 5 through 9 major shots. Other workflow profiles must declare their own bounds; absence of an applicable profile rule fails closed.

### Identity domains

Beat, Shot, and Panel identifiers are separate domains with independent sequences:

- beats use `B01`, `B02`, and a contiguous `beat_sequence`;
- shots use `S01`, `S02`, and a contiguous `shot_sequence`;
- panels use the parent-scoped form `S04-P01`, `S04-P02`, and a contiguous `panel_sequence` within each Shot.

IDs and sequences must both be unique and contiguous. Every Shot belongs to exactly one Beat. Every Panel's `beat_id` and `shot_id` must equal its parent values. Multiple Panels do not create additional Shots and cannot hide a missing Shot sequence.

Shots belonging to one Beat must form one contiguous Shot span. Beat timing is derived from the first and last Shot belonging to the Beat. A Beat must not publish an independently maintained timing range that could conflict with its Shots.

### Shot timing

All authoritative timing uses integer milliseconds:

- `start_ms`
- `end_ms`
- `duration_ms`

The first Shot starts at zero. Each following Shot starts at the previous Shot's `end_ms`. Shots have no gaps or overlaps. For every Shot, `end_ms - start_ms` equals `duration_ms`. The sum of all Shot durations and the final `end_ms` must both equal `total_duration_ms`.

Visual transitions do not overlap the main Shot timeline. The required `transition` object carries `kind`, `duration_ms`, and `timing_policy`, such as consuming the tail of the source Shot or the head of the destination Shot. An explicit no-transition value uses `kind: none`, `duration_ms: 0`, and `timing_policy: none`.

### Panel timing modes

Every Panel declares one of two timing modes:

`TEMPORAL_SEGMENT`

- requires `start_ms`, `end_ms`, and `duration_ms`;
- must remain inside its parent Shot;
- sibling temporal segments must be contiguous, non-overlapping, and cover the entire parent Shot.

`KEYFRAME_ANCHOR`

- requires `anchor_time_ms` and `anchor_role`;
- the anchor time must remain inside its parent Shot;
- must not publish a duration or claim temporal coverage;
- may coexist with temporal segments or other distinct keyframe anchors.

The rendered sheet labels each cell with its timing mode. A temporal segment displays start, end, and duration. A keyframe anchor displays anchor time and role.

### Required Shot semantics

Every Shot requires all 14 fields:

1. `start_state`
2. `action_path`
3. `end_state`
4. `emotion_transition`
5. `audience_psychology`
6. `conversion_function`
7. `dialogue_or_voiceover`
8. `subtitle`
9. `sound_design`
10. `transition`
11. `required_assets`
12. `forbidden_assets`
13. `first_frame_role`
14. `provider_reference_role`

Empty audio, dialogue, subtitle, or transition intent must be represented by an explicit semantic value such as `none`, not by a missing field.

### Camera and subject motion

Camera and subject motion are separate objects. Each contains:

- a structured text definition;
- a visual annotation with an accessible text label;
- a non-color encoding such as line style, marker shape, or arrow form;
- an optional color that is never the sole distinction.

Using the same color is permitted only when the annotations remain distinguishable without color. Identical unlabeled color-only arrows fail closed.

### Product scope and continuity

The plan and every Shot carry:

- `active_product_id`
- `active_sku_id`
- `visible_sku_ids`
- `forbidden_sku_ids`
- `product_state`
- `package_state`
- `container_state`
- `scale_constraints`

The enclosing `product_scope.mode` is `single_sku` or `multi_sku`.

For `single_sku`, visible SKU values may contain only `active_sku_id`. For `multi_sku`, `allowed_sku_ids` is mandatory and every active or visible SKU must be allowed. `multi_sku` is valid only when the input `TaskSpec.constraints.storyboard.product_scope` explicitly declares `mode: multi_sku` and the allowed SKU set. An agent cannot upgrade a single-SKU task.

Product, character, wardrobe, scene, package, container, and scale transitions must either remain continuous or have an explicit approved transition declaration.

## Production Storyboard Panel Set

`ProductionStoryboardPanelSet` contains only independent production Panels. Analysis boards, evidence boards, replication boards, contact sheets, and storyboard master sheets are never production Panels.

Each Panel entry separates two layers.

`panel_asset_facts` contains image facts:

- `panel_asset_id`
- media type and task-local asset location
- byte size and SHA-256
- pixel dimensions and aspect ratio
- rendered product/SKU identity
- generation status
- approval status and QA status
- generation configuration and exact source asset hashes

`plan_binding_summary` contains the source-plan binding:

- plan artifact ID, revision, schema version, and digest
- `beat_id`, `shot_id`, and `panel_id`
- timing mode and its timing projection
- semantic provenance
- approved continuity and product-scope references

Every Panel must bind a current `VisualQAAttestation` or `HumanApprovalRecord`. The record must reference the exact `panel_asset_id` and current asset SHA-256, identify the visual dimensions assessed, carry an approval decision, and be effective at validation time. Metadata or provenance claims alone cannot establish real visual consistency. Missing, expired, revoked, or hash-mismatched evidence fails closed.

## Video Generation Storyboard Master

`VideoGenerationStoryboardMaster` is a validated execution projection of the production plan plus execution-only fields. It is not a full mechanical copy of the Plan. It retains only semantics needed to execute and review the video while binding all source revisions and digests.

Each `master_panel_entry` binds exactly one approved `panel_asset_id`. A Shot may contain multiple entries. The builder rejects:

- duplicate asset bindings;
- missing or orphaned Panels;
- `panel_id` / `panel_asset_id` conflicts;
- non-approved or failed-QA assets;
- aspect-ratio disagreement;
- rendered identity disagreement;
- stale or mismatched visual attestations;
- semantic provenance disagreement;
- incompatible schema versions.

## Programmatic Storyboard Sheets

### Authority and pagination

Sheets are read-only PNG views of Master JSON. They never become semantic input.

Panels are ordered by Shot and Panel sequence. Each horizontal sheet contains at most nine Panel cells. Panels from the same Shot remain adjacent. When a Shot crosses a page boundary, the next page repeats the Shot ID and labels it `continued`.

Each cell preserves the target video aspect ratio for the independent Panel image. Text and annotations are rendered outside the image frame.

### Layout

The header contains:

- project name
- platform
- target aspect ratio
- total duration
- active Product/SKU scope
- core narrative formula
- version and approval status

Each cell contains:

- Shot, Panel, and Beat IDs
- `timing_mode` and the mode-specific time representation
- the approved independent Panel image
- shot size and camera position
- camera motion and subject motion
- start state and end state
- emotion transition and conversion function
- dialogue/voiceover, subtitle, sound, and transition
- first-frame and Provider-reference roles
- QA state

The footer contains:

- Narrative Arc
- Emotion Arc
- Conversion Arc
- Continuity Chain
- Duration Validation
- Artifact Provenance

### Sheet outputs and execution policy

Video Planning writes:

- `video_generation_storyboard_master.json`
- `storyboard_master_sheet_001.png` and later pages as required
- `storyboard_master_sheet_manifest.json`
- the existing `shot_motion_plan.json`
- the existing `video_execution_package.json`
- the existing `first_frame_mapping.json`
- the existing `reference_role_mapping.json`
- the existing provenance output

The sheet manifest records each page name, Panel IDs, layout version, input Master digest, PNG SHA-256, and page metadata. The same execution policy is written in:

1. the sheet manifest;
2. each page's PNG metadata;
3. the Master JSON `sheet_outputs` section.

The policy is always:

```json
{
  "role": "human_review_only",
  "first_frame_eligible": false,
  "provider_execution_input": false,
  "semantic_authority": false
}
```

No module may OCR a sheet or use it to write back semantic fields.

## Execution Mappings

`FirstFrameMapping` references only a clean, approved, QA-passing independent Panel whose aspect ratio matches the target. It never references a contact sheet, storyboard sheet, grid, label-bearing composite, or analysis board.

`ReferenceRoleMapping` accepts only explicitly allowlisted Provider roles. An asset with an absent, unknown, or inferred role cannot enter Provider execution input. Reference analysis boards may be structural review context only and remain non-executable.

Any hard-rule failure prevents issuance of:

- `VideoExecutionPackage`
- `FirstFrameMapping`
- `ReferenceRoleMapping`
- any Provider execution input

## Fail-Closed QA

### Four validation layers

1. Storyboard blocks invalid profiles, identity sequences, timing, hierarchy, semantics, SKU scope, motion annotations, and continuity before publishing plans.
2. Image Panel blocks invalid assets, analysis-board substitution, plan-binding mismatch, missing asset facts, and invalid visual evidence before publishing PanelSet.
3. Video Planning blocks invalid execution projections, approvals, bindings, mappings, continuity, and sheet metadata before publishing execution artifacts.
4. QA / Review independently revalidates immutable artifacts and publishes only a structured QA report.

### QA report

The final verdict is `PASS` or `FAIL`. The report includes:

- report artifact ID and schema version
- ruleset ID and ruleset version
- QA code commit
- execution environment identity
- complete input artifact IDs, revisions, schema versions, and digests
- verdict
- `findings[]`, each with `error_code`, `severity`, `artifact_id`, and `field_paths`
- execution-readiness decision
- creation time and report digest

Any input revision, digest, schema, ruleset, QA commit, or execution-environment change makes an older PASS inapplicable to the new evaluation set.

QA is read-only for owner artifacts and PNG files. It may write only its own report directory. Tests compare every owner artifact and PNG hash before and after QA.

### Failure lifecycle

An upstream hard-rule failure prevents downstream artifacts from being generated.

If already generated artifacts later fail QA, their execution readiness is removed while their bytes and audit evidence are retained:

- `INVALIDATED` is the derived state when current QA fails, visual evidence expires, or an input/ruleset changes;
- `REVOKED` is the state when an authorized revocation record explicitly withdraws a prior approval.

Both states prohibit Provider input. QA records the status in its report and readiness decision; it does not mutate the owner artifact.

### Stable error families

Implementation must expose stable codes and exact field paths for at least:

- duration mismatch and timeline discontinuity
- missing or duplicate Beat/Shot/Panel identities
- invalid Panel timing mode
- unauthorized or mixed SKU scope
- missing Shot execution semantics
- insufficient motion annotation
- missing, expired, revoked, or mismatched visual evidence
- unapproved or inconsistent Panel bindings
- forbidden board/contact-sheet roles
- incompatible schema versions
- stale revisions or old QA PASS
- continuity conflicts
- sheet manifest, metadata, or digest mismatch

## Regression Acceptance

Tests must cover all of these cases:

1. A 15-second title with Shots totaling 17 seconds fails.
2. `S01`, `S02`, `S03`, `S04`, `S06` fails even when `S04` has `S04-P01/P02/P03`.
3. Three visible SKUs in a single-SKU reveal fail.
4. Same-color camera and subject arrows without non-color distinction fail.
5. Missing exact Shot start/end time fails.
6. Missing dialogue/voiceover, subtitle, sound, or transition semantics fails.
7. Temporal Panel segments that do not cover their parent Shot fail.
8. A keyframe Panel with a duration or an out-of-range anchor fails.
9. Contact sheet first-frame, analysis-board Panel, and non-allowlisted Provider roles fail.
10. Unauthorized product, SKU, character, wardrobe, scene, package, container, or scale changes fail.
11. Ten Panels render two sheets; no sheet exceeds nine cells and a split Shot is marked `continued`.
12. Manifest, page metadata, and Master all carry the same non-executable sheet policy.
13. A changed PNG or source digest fails without OCR or semantic writeback.
14. Duplicate asset bindings, missing Panels, orphaned Panels, and conflicting Panel/asset IDs fail.
15. Incompatible schema versions and an old-revision QA PASS fail.
16. A visual attestation with the wrong asset hash fails.
17. QA leaves all owner artifact and PNG hashes unchanged and writes only to its report directory.
18. Fake/offline acceptance proves zero real image and video Provider network calls.

## Implementation Constraints

- Preserve existing registered artifact names and versions.
- Keep all validation deterministic and Provider-neutral.
- Reuse owner public interfaces; do not introduce private cross-Skill imports.
- Render sheets programmatically from task-local independent Panel bytes and validated JSON.
- Do not add OCR, image-to-structure inference, or semantic sheet parsing.
- Do not call a real image or video Provider.
- Use versioned synthetic fixtures when upstream artifacts are unavailable.

## Completion Evidence

Implementation is complete only when owner tests for all four layers pass, the full offline suite passes, the renderer pagination and PNG metadata are verified, owner artifacts remain unchanged across QA, and network-call counters remain zero.
