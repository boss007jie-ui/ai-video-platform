---
name: storyboard
version: 1.3.0
status: review
---

# Storyboard Skill

## Responsibility

Create and revise deterministic Story/Scene/Beat/Shot/Panel plans; decompose raw scripts into bounded automatic shot/panel plans; validate hierarchy, typed character/product/scene/prop continuity archives, emotional progression, configured `required_color`/`logo_visibility` product constraints, and declared continuity transitions. This Skill never generates images or video, submits or downloads Provider work, imports Planning implementation, or writes Product/Research Library state.

The production-planning boundary translates optional `ReferenceStoryboardAnalysis` and `ReplicationPattern` mechanisms into the current `ProductContextBundle`. Reference pacing, camera, emotion, audience-psychology, and conversion mechanics may influence the plan; reference people, brands, products, packaging, protected identities, analysis boards, and evidence boards never become production identity or required panel assets.

## Public commands

- `create-storyboard`: create version 1 with `expected_version: 0` and no prior artifact; a plan containing `raw_script` is materialized automatically.
- `create-storyboard-from-script`: explicit raw-script alias; accepts top-level CLI `raw_script`, optional `planning_options`, and optional `continuity_archive`.
- `revise-storyboard`: create the next immutable version from `prior_artifact` and an exact `expected_version`.
- `validate-continuity`: validate one serialized owner-local artifact through CLI or `StoryboardService.validate_continuity(artifact)` with no side effects.
- `derive-production-panels`: publish the canonical `ProductionStoryboardPlan` and `ProductionStoryboardPanelPlan` `1.0.0` business artifacts under an explicit output root. Prefer passing the approved owner-local `storyboard_artifact`; the Skill then generates production IDs, timing, motion annotations, continuity fields, and downstream `shots` automatically. The legacy hand-authored `production_constraints.structured_plan` input remains supported.

CLI entry point:

```text
python -m ai_video_platform.skills.storyboard.cli create-storyboard --input request.json
python -m ai_video_platform.skills.storyboard.cli create-storyboard-from-script --input request.json
python -m ai_video_platform.skills.storyboard.cli revise-storyboard --input request.json
python -m ai_video_platform.skills.storyboard.cli validate-continuity --input artifact.json
python -m ai_video_platform.skills.storyboard.cli derive-production-panels --input request.json
```

The CLI writes exactly one compact UTF-8 JSON result to stdout. Create/revise request JSON must include explicit `task_workspace` and `state_file` paths; `task_workspace` must resolve to the operator-configured `AVP_TASK_WORKSPACE_ROOT` (or the CLI working directory when unset), and the resolved state path must remain inside it. The owner-local atomic state store provides cross-process exact replay and stale compare-and-set. Exit `0` means completed/cancelled; exit `2` means a stable validation, compatibility, reference, conflict, authorization, or state rejection.

## Inputs and outputs

Required inputs are approved Foundation Contract envelopes: `TaskSpec`, `TaskContext`, and confirmed `ProductContextBundle`. Optional reference consumption is only through `ReferenceManifest`; a private Reference Analysis object is not accepted. Create/revise also receives an owner-local plan object and idempotency/version fields. A raw-script request may omit `scenes`; the Skill deterministically creates 6-12 Panels (default derived within that band), including `panel_type`, `layout`, and `key_moment`. Structured plan callers remain compatible. Typed continuity uses an additive `continuity_archive.entities` list with character, product, scene, and prop records plus validated entity relationships; generic per-Panel `continuity` remains valid.

Legacy create/revise outputs remain an immutable owner-local `StoryboardArtifact`, task-owned `AssetManifest` reference, `FeedbackEvent`, and `SkillExecutionEvent`. `StoryboardArtifact.artifact_kind = storyboard-owner-local-draft` remains an implementation detail.

`derive-production-panels` publishes exactly these registered business identities without presenting them as Foundation `ContractEnvelope` types whose schemas are still pending: `ProductionStoryboardPlan` (`avp.contract.production-storyboard-plan`, `1.0.0`) and `ProductionStoryboardPanelPlan` (`avp.contract.production-storyboard-panel-plan`, `1.0.0`). It writes:

```text
production_storyboard_plan/
  production_storyboard_plan.json
  production_storyboard_panel_plan.json
```

For the preferred path, Hermes supplies `task_spec`, `product_context`, the already-created `storyboard_artifact`, `production_constraints.duration_ms`, optional `production_constraints.aspect_ratio`, and `output_root`. Hermes must not reconstruct `beat_id`, `shot_id`, timing, motion annotations, or continuity objects. Supplying both `storyboard_artifact` and the legacy `production_constraints.structured_plan` is rejected.

The production plan contains `NarrativeArc`, `ScenePlan`, `BeatPlan`, `ShotPlan`, `EmotionArc`, `AudiencePsychologyArc`, `ConversionArc`, `ContinuityBible`, and `ProductStateTimeline`. Every panel binds ordered timing and frozen moment, camera/framing, current character/product/packaging/container state, emotion, approved/forbidden assets, scale constraints, continuity references, and reference-mechanism provenance.

All artifacts retain source Contract IDs and payload SHA-256 digests. The task `AssetManifest` records the Storyboard content hash, canonical byte size, URI, and provenance.

## Invariants and ordering

1. Validate Foundation envelopes and publisher permissions.
2. Confirm one task, active Skill `storyboard`, product/SKU identity, reference requirement, and expected version.
3. Honour cancellation before creating a business artifact.
4. Enforce 1 MiB canonical input and 500 Panel budgets.
5. Reject Provider/image/video capability keys.
6. Materialize raw-script requests with an explicit 6-12 Panel bound and deterministic scene/beat/shot allocation.
7. Validate non-empty hierarchy, unique IDs, non-regressing emotion scores, typed continuity identities/relationships, configured `required_color`/`logo_visibility` constraints, and exact generic continuity transitions.
8. Emit immutable outputs, then record the idempotent result.

Same idempotency key plus same request digest replays the atomically recorded object without repeating output construction, including across CLI processes that share the explicit state file. The same key with a different digest fails. Cross-process create/revise also uses atomic version compare-and-set, so a second writer against an old version fails stale. Retry is caller-controlled and only safe with the same key and exact input. No automatic network or Provider retry exists.

## Read/write boundary and side effects

- Reads only supplied immutable Contracts and owner-local request data.
- Writes no Product Library, Research Library, Legacy root, other Skill state, or Provider boundary.
- The in-process default uses an in-memory atomic state store. CLI create/revise binds `task_workspace` to the operator environment (falling back to the process working directory), resolves `state_file`, rejects escape/Legacy paths, and atomically updates only that state file; it also reads its explicit request file/stdin and writes stdout. The state file has an 8 MiB fail-before-write budget.
- All timestamps use an injectable clock; deterministic fixtures use a fixed UTC clock.

## Stable errors

Public codes include: `STORYBOARD_COMMAND_UNSUPPORTED`, `STORYBOARD_INPUT_INVALID`, `STORYBOARD_CONTRACT_INVALID`, `STORYBOARD_CONTEXT_INVALID`, `STORYBOARD_REFERENCE_REQUIRED`, `PRODUCT_SKU_AMBIGUOUS`, `STORYBOARD_VERSION_STALE`, `STORYBOARD_IDEMPOTENCY_CONFLICT`, `STORYBOARD_PLAN_INCOMPLETE`, `STORYBOARD_ID_DUPLICATE`, `STORYBOARD_PRODUCT_MISMATCH`, `STORYBOARD_PRODUCT_CONSTRAINT_VIOLATION`, `STORYBOARD_EMOTIONAL_PROGRESSION_INVALID`, `STORYBOARD_CONTINUITY_CONFLICT`, `STORYBOARD_CONTINUITY_ENTITY_INVALID`, `STORYBOARD_PLANNING_INVALID`, `STORYBOARD_CAPABILITY_FORBIDDEN`, `STORYBOARD_BUDGET_EXCEEDED`, `STORYBOARD_STATE_STORE_REQUIRED`, `STORYBOARD_STATE_PATH_FORBIDDEN`, `STORYBOARD_STATE_CORRUPTED`, `STORYBOARD_STATE_UNAVAILABLE`, `STORYBOARD_STATE_BUDGET_EXCEEDED`, and `STORYBOARD_STATE_LOCK_TIMEOUT`. Foundation validation codes are preserved without secret-bearing details.

## Fake/rejecting modes

`StoryboardService(clock=...)` plus synthetic Foundation envelopes is the deterministic fake/local mode. Any Provider/image/video submission-shaped key is a rejecting boundary and fails before output creation. There is no production Provider adapter because Provider access is outside Storyboard ownership.

## Tests

```text
python -m unittest -v tests.skills.storyboard.test_storyboard_interface
python -m unittest -v tests.skills.storyboard.test_storyboard_continuity
python -m unittest -v tests.skills.storyboard.test_storyboard_failures
python -m unittest -v tests.skills.storyboard.test_storyboard_features
python tools\run_offline_tests.py
```

## Hermes example

Hermes creates approved Foundation envelopes, then invokes the public CLI with a branch-local plan. It routes returned Contract envelopes by ID and never imports `domain.py` or `interface.py` internals. Missing input fails closed; Storyboard does not invoke Reference Analysis, Product Knowledge, Planning, or generation Skills implicitly.

## Maintenance

Owner: `codex-03`, current work item `FT-03-001`, branch `ft/codex-03-storyboard`. Source/tests/docs must remain under the Codex-03 owner allowlist. Shared Contract/Core/root CLI/release changes are requests to Codex-00.
