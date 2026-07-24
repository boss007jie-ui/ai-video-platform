# Storyboard Artifact Chain V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the frozen structured storyboard, selected production PanelSet, deterministic storyboard master sheets, and independent read-only QA chain without real Provider or network access.

**Architecture:** Preserve the four existing producers. Each producer validates its owned boundary and publishes a deterministic projection for the next producer; QA independently validates immutable owner artifacts and never mutates them.

**Tech Stack:** Python 3.14 standard library, immutable JSON mappings, deterministic PNG encoding/decoding with `struct` and `zlib`, `unittest`, existing owner CLIs.

## Global Constraints

- Keep all 13 canonical Business Artifact identities and `1.0.0` versions unchanged; add no aliases.
- Use the frozen `STRUCTURED_STORYBOARD_PLAN_CONTRACT_V1`, `VIDEO_GENERATION_STORYBOARD_MASTER_RENDERING_CONTRACT_V1`, and `STORYBOARD_ARTIFACT_CHAIN_FAIL_CLOSED_QA_V1` semantics.
- Keep fake/offline execution, zero real image/video Provider calls, zero network calls, and `provider_smoke: NOT_REQUIRED`.
- Do not use OCR. Sheets are non-authoritative, human-review-only, and never Provider inputs.
- QA may write only its report directory and may not mutate owner artifacts or PNG files.
- A formal `ProductionStoryboardPanelSet` contains only `usage_status: SELECTED` Panels.
- Human approval maps to existing `ApprovalRecord`; visual QA attestation maps to a formal QA artifact/report.

---

### Task 1: Update Existing Increment Task Cards

**Files:**
- Modify: `../AI Video Platform Re-architecture Control/PARALLEL_LAUNCH_PACK/task_cards/TASK_DELTA_CODEX_03_STORYBOARD.md`
- Modify: `../AI Video Platform Re-architecture Control/PARALLEL_LAUNCH_PACK/task_cards/TASK_DELTA_CODEX_04_IMAGE_PANEL.md`
- Modify: `../AI Video Platform Re-architecture Control/PARALLEL_LAUNCH_PACK/task_cards/TASK_DELTA_CODEX_05_VIDEO_PLANNING.md`
- Modify: `../AI Video Platform Re-architecture Control/PARALLEL_LAUNCH_PACK/task_cards/TASK_DELTA_CODEX_06_QA.md`

**Interfaces:**
- Consumes: the approved design at `docs/superpowers/specs/2026-07-24-storyboard-artifact-chain-design.md`.
- Produces: four owner-specific frozen implementation deltas without new identities, work items, branches, worklines, or Skills.

- [ ] **Step 1: Append the Codex-03R frozen delta**

State the structured hierarchy, profile-scoped Shot count, ID/sequence rules, integer timeline, two Panel timing modes, 14 Shot fields, explicit TaskSpec multi-SKU authorization, motion accessibility, and fail-closed regression cases.

- [ ] **Step 2: Append the Codex-04R frozen delta**

State selected-only PanelSet publication, `panel_asset_facts` / `plan_binding_summary` separation, exact hash-bound ApprovalRecord or QAReport evidence, and exclusion of failed/alternate/discarded/superseded images.

- [ ] **Step 3: Append the Codex-05 frozen delta**

State validated Master projection, exact approved Panel bindings, explicit mappings, deterministic multi-page PNG sheet metadata, and three-layer non-executable policy.

- [ ] **Step 4: Append the Codex-06 frozen delta**

State structured QAReport fields, full evaluation-set binding, invalidation/revocation readiness semantics, read-only hash checks, visual evidence validation, and reference-integrity regressions.

- [ ] **Step 5: Verify card identities are unchanged**

Run: `rg -n "authorization_id|work_item_id|workline_id|branch:" PARALLEL_LAUNCH_PACK/task_cards/TASK_DELTA_CODEX_0*.md`

Expected: the existing FTG/work item/workline/branch values remain present and no new identity is introduced.

### Task 2: Codex-03R Structured Plan and PanelPlan

**Files:**
- Create: `src/ai_video_platform/skills/storyboard/structured_plan.py`
- Modify: `src/ai_video_platform/skills/storyboard/production.py`
- Modify: `tests/skills/storyboard/test_production_storyboard.py`

**Interfaces:**
- Consumes: `TaskSpec.constraints.storyboard`, `ProductContextBundle`, production constraints, and optional reference artifacts.
- Produces: `validate_structured_storyboard(plan, task_spec) -> dict[str, object]` and enriched `ProductionStoryboardPlan` / `ProductionStoryboardPanelPlan` projections.

- [ ] **Step 1: Write failing structured-plan regression tests**

Add table-driven tests for 15s/17s mismatch, missing `S05`, unauthorized multi-SKU reveal, color-only motion distinction, missing exact times, missing each required execution field, Beat mismatch, invalid transition overlap policy, temporal coverage gaps, and invalid keyframe anchors.

```python
with self.assertRaises(StoryboardError) as captured:
    validate_structured_storyboard(candidate, task_spec_payload)
self.assertEqual(captured.exception.code, expected_code)
self.assertEqual(captured.exception.field_paths, expected_paths)
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest tests.skills.storyboard.test_production_storyboard -v`

Expected: failures because `validate_structured_storyboard` and the new projections do not exist.

- [ ] **Step 3: Implement the validator**

Create focused helpers for JSON object/text/integer validation, profile limits, identity sequences, Shot timeline, Panel timing modes, 14 required fields, transition policy, TaskSpec SKU authorization, motion annotations, and continuity. Return a deep JSON snapshot; never mutate input.

- [ ] **Step 4: Project validated data into both artifacts**

Make `ProductionStoryboardPlan.shots` carry the validated execution semantics and make `ProductionStoryboardPanelPlan.panels` carry parent IDs, timing mode, camera/subject annotations, product scope, asset constraints, and plan revision/digest provenance.

- [ ] **Step 5: Run owner tests and commit**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest tests.skills.storyboard.test_production_storyboard tests.skills.storyboard.test_storyboard_continuity tests.skills.storyboard.test_storyboard_failures tests.skills.storyboard.test_storyboard_features tests.skills.storyboard.test_storyboard_interface -v`

Expected: PASS with no Provider or network access.

Commit: `feat(storyboard): enforce structured production plan contract`

### Task 3: Codex-04R Selected Independent PanelSet

**Files:**
- Modify: `src/ai_video_platform/skills/product_image_panel_generation/errors.py`
- Modify: `src/ai_video_platform/skills/product_image_panel_generation/storyboard_panels.py`
- Modify: `tests/skills/product_image_panel_generation/fixtures/production-storyboard-panel-plan-v1.json`
- Modify: `tests/skills/product_image_panel_generation/fixtures/approved-storyboard-assets-v1.json`
- Modify: `tests/skills/product_image_panel_generation/test_storyboard_panel_artifacts.py`

**Interfaces:**
- Consumes: enriched `ProductionStoryboardPanelPlan`, independent generated asset bytes, ApprovalRecord mappings, and QAReport/visual attestation mappings.
- Produces: selected-only `ProductionStoryboardPanelSet` entries with `panel_asset_facts` and `plan_binding_summary`.

- [ ] **Step 1: Write failing selected/evidence tests**

Test rejection of `ALTERNATE`, `FAILED`, `DISCARDED`, and `SUPERSEDED` usage statuses; missing evidence; expired/revoked evidence; asset-ID/hash mismatch; duplicate binding; and old timing/hierarchy projections.

```python
self.assertEqual(panel_set["panels"][0]["usage_status"], "SELECTED")
self.assertIn("panel_asset_facts", panel_set["panels"][0])
self.assertIn("plan_binding_summary", panel_set["panels"][0])
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest tests.skills.product_image_panel_generation.test_storyboard_panel_artifacts -v`

Expected: failures because selected-only and evidence-bound layered records are absent.

- [ ] **Step 3: Implement selected-only evidence validation**

Accept only evidence kinds `ApprovalRecord` and `QAReport`; require exact `panel_asset_id`, asset SHA-256, approved/PASS decision, effective interval, and non-revoked state. Do not invent a new approval Contract.

- [ ] **Step 4: Emit layered PanelSet records**

Keep image bytes and hashes in `panel_asset_facts`; keep plan IDs, timing, semantic provenance, continuity, and source plan digest in `plan_binding_summary`. Exclude every non-selected generation from the formal PanelSet while retaining generation failures in the owner QA/provenance outputs.

- [ ] **Step 5: Run owner tests and commit**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_adapters tests.skills.product_image_panel_generation.test_image_panel_architecture tests.skills.product_image_panel_generation.test_image_panel_interface tests.skills.product_image_panel_generation.test_image_panel_safety tests.skills.product_image_panel_generation.test_storyboard_panel_artifacts tests.skills.product_image_panel_generation.test_yunwu_adapters`

Expected: PASS; rejecting and fake paths remain deterministic and network-free.

Commit: `feat(image-panel): publish selected evidence-bound panel set`

### Task 4: Codex-05 Master Projection, Mappings, and PNG Sheets

**Files:**
- Create: `src/ai_video_platform/skills/storyboard_master_video_planning/sheet_renderer.py`
- Modify: `src/ai_video_platform/skills/storyboard_master_video_planning/interface.py`
- Modify: `src/ai_video_platform/skills/storyboard_master_video_planning/cli.py`
- Modify: `src/ai_video_platform/skills/storyboard_master_video_planning/errors.py`
- Modify: `tests/skills/storyboard_master_video_planning/test_video_planning_interface.py`
- Modify: `tests/skills/storyboard_master_video_planning/test_video_planning_failures.py`

**Interfaces:**
- Consumes: validated plan projection, selected PanelSet, panel bytes keyed by asset ID, ProductContextBundle, and explicit allowed reference roles.
- Produces: canonical Master/mappings/package JSON plus `render_storyboard_sheets(master, panel_bytes, metadata) -> (manifest, pages)`.

- [ ] **Step 1: Write failing Master binding and mapping tests**

Cover duplicate/missing/orphaned/conflicting Panel bindings, approval/QA/aspect/rendered-identity/provenance mismatches, incompatible schema, dirty first frame, inferred Provider role, and hard-rule suppression of all execution artifacts.

- [ ] **Step 2: Write failing deterministic renderer tests**

Build ten synthetic Panels and assert two pages, at most nine cells, adjacent same-Shot Panels, `continued`, preserved image aspect ratio, mode-specific timing labels, accessible motion encodings, three-layer execution policy, page SHA-256, and byte-for-byte replay.

```python
self.assertEqual(first_render.pages, second_render.pages)
self.assertEqual(manifest["renderer_version"], "1.0.0")
self.assertFalse(manifest["execution_policy"]["provider_execution_input"])
```

- [ ] **Step 3: Run planning tests and confirm RED**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest tests.skills.storyboard_master_video_planning.test_video_planning_interface tests.skills.storyboard_master_video_planning.test_video_planning_failures -v`

Expected: failures because selected layered bindings and deterministic multi-page rendering are absent.

- [ ] **Step 4: Implement validated execution projection**

Project only execution-required plan semantics. Require one selected approved asset per `master_panel_entry`; verify evidence, hashes, rendered identity, aspect ratio, semantic provenance, revision, and order before constructing any downstream artifact.

- [ ] **Step 5: Implement local deterministic PNG renderer**

Use standard-library PNG parsing/encoding. Render actual Panel pixels into fixed cells with metadata outside the image frames. Embed `renderer_version`, `renderer_code_commit`, `layout_version`, `font_family`, `font_fallback`, `locale`, `render_width`, `render_height`, Master digest, page index, and execution policy. Do not import another Skill's private renderer.

- [ ] **Step 6: Replace the constant PNG CLI output**

Write `storyboard_master_sheet_NNN.png` pages and `storyboard_master_sheet_manifest.json`. Remove the old constant `video_storyboard_master.png` output. Use exclusive atomic output creation and task-workspace path checks.

- [ ] **Step 7: Run owner tests and commit**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest tests.skills.storyboard_master_video_planning.test_video_planning_interface tests.skills.storyboard_master_video_planning.test_video_planning_failures tests.skills.video_generation.test_video_generation_safety tests.skills.video_generation.test_video_generation_interface -v`

Expected: PASS and no Provider submission.

Commit: `feat(video-planning): render deterministic storyboard master sheets`

### Task 5: Codex-06 Independent Read-Only QA

**Files:**
- Modify: `src/ai_video_platform/skills/qa_review/storyboard_chain.py`
- Modify: `src/ai_video_platform/skills/qa_review/models.py`
- Modify: `src/ai_video_platform/skills/qa_review/interface.py`
- Modify: `src/ai_video_platform/skills/qa_review/cli.py`
- Modify: `tests/skills/qa_review/test_storyboard_artifact_chain.py`

**Interfaces:**
- Consumes: immutable owner artifacts, Panel/Sheet PNG hashes, ApprovalRecord/QAReport evidence, ruleset identity, QA commit, and execution environment.
- Produces: `StoryboardArtifactChainQAReport` with PASS/FAIL, structured findings, complete evaluation-set binding, readiness state, and deterministic digest.

- [ ] **Step 1: Write failing QA report/lifecycle tests**

Assert report fields, findings with error code/severity/artifact/field paths, full input revision/digest/schema set, ruleset/commit/environment binding, old-PASS invalidation, `INVALIDATED` and `REVOKED` readiness, and suppression of Provider inputs.

- [ ] **Step 2: Write failing read-only/reference-integrity tests**

Hash all owner JSON/PNG inputs before and after QA; assert equality and that only the QA report directory changes. Cover duplicate binding, missing/orphaned Panel, conflicting IDs, schema incompatibility, stale revision PASS, and visual evidence hash mismatch.

- [ ] **Step 3: Run QA tests and confirm RED**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest tests.skills.qa_review.test_storyboard_artifact_chain -v`

Expected: failures because evaluation-set binding and lifecycle/read-only reporting are absent.

- [ ] **Step 4: Implement structured read-only QA**

Extend findings without mutating artifacts. Validate real visual consistency only through current hash-bound ApprovalRecord or formal QAReport evidence. Compute readiness from the current evaluation set; preserve audit evidence on FAIL.

- [ ] **Step 5: Run owner tests and commit**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest tests.skills.qa_review.test_qa_review_evaluation tests.skills.qa_review.test_qa_review_interface tests.skills.qa_review.test_qa_review_permissions tests.skills.qa_review.test_storyboard_artifact_chain -v`

Expected: PASS; filesystem diff is limited to QA report outputs.

Commit: `feat(qa): enforce read-only storyboard chain readiness`

### Task 6: Integration Verification and Merge Report

**Files:**
- Modify: `docs/superpowers/specs/2026-07-24-storyboard-artifact-chain-design.md` only if implementation reveals a non-semantic clarification; otherwise leave frozen.

**Interfaces:**
- Consumes: all four owner increments.
- Produces: a final repository commit sequence and merge-ready evidence report.

- [ ] **Step 1: Run all four owner suites**

Run the exact commands from Tasks 2 through 5 and record Ran/skipped counts.

- [ ] **Step 2: Run full offline verification**

Run: `$env:PYTHONPATH=$null; py -3.14 tools\run_offline_tests.py`

Expected: PASS with zero failures; only documented platform skips are allowed.

- [ ] **Step 3: Verify network/provider/OCR boundaries**

Run: `rg -n "OCR|pytesseract|Provider.*submit|requests|httpx|urllib|socket" src/ai_video_platform/skills/storyboard src/ai_video_platform/skills/product_image_panel_generation/storyboard_panels.py src/ai_video_platform/skills/storyboard_master_video_planning src/ai_video_platform/skills/qa_review/storyboard_chain.py`

Expected: no new OCR or network seam and no Planning/QA Provider submission.

- [ ] **Step 4: Verify repository state**

Run: `git diff --check; git status --short; git log --oneline -8`

Expected: no whitespace errors, intended changes only, and one focused commit per owner stage.

- [ ] **Step 5: Report merge evidence**

Report branch, start/end SHA, changed paths, exact commands, Ran/skipped counts, artifact names, task-card updates, blockers, `provider_smoke: NOT_REQUIRED`, and network-call counters equal to zero. Do not run a real Provider smoke.
