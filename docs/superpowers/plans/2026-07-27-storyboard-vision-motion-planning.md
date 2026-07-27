# Storyboard Vision Motion Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Agent-supplied per-Panel visual observations plus Master script semantics into deterministic in-frame camera and subject arrow paths.

**Architecture:** Add an owner-local `motion_planner.py` that validates visual observations, extracts supported script intents, reconciles intent with observed objects/contacts/candidates, and returns renderer-ready normalized paths. The CLI invokes the planner before rendering when observations are present; the renderer remains deterministic and Provider-free.

**Tech Stack:** Python 3.12+ standard library, existing unittest/pytest suite, existing standard-library PNG renderer.

## Global Constraints

- Modify only `storyboard_master_video_planning`, its owned tests, and its local documentation.
- Do not change frozen contracts or canonical `VideoGenerationStoryboardMaster` semantics.
- Do not call image/video Providers, read credentials, or use the network.
- Visual observations and planned paths stay in sheet render metadata.
- Missing, low-confidence, or conflicting observations must produce no guessed in-frame arrow.
- The sheet remains human-review-only and first-frame-ineligible.

---

### Task 1: Visual Observation Validation and Script Intent Extraction

**Files:**
- Create: `src/ai_video_platform/skills/storyboard_master_video_planning/motion_planner.py`
- Create: `tests/skills/storyboard_master_video_planning/test_motion_planner.py`

**Interfaces:**
- Consumes: Master mappings and `panel_visual_observations` keyed by `panel_id`.
- Produces: `plan_motion_annotations(master: Mapping[str, Any], observations: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]`.

- [ ] **Step 1: Write failing validation and intent tests**

Test that normalized object boxes, contacts, and motion candidate points are accepted; out-of-range coordinates raise `ValueError`. Test that `locked macro, slight push-in` extracts camera `push`, while `locked close-up` extracts no camera movement. Test subject intents for press, squeeze, rotate, enter-left, lift/release, and hold.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/skills/storyboard_master_video_planning/test_motion_planner.py -q`

Expected: collection failure because `motion_planner` does not exist.

- [ ] **Step 3: Implement minimal parser and validation**

Create immutable normalized helpers for points and `[left, top, right, bottom]` boxes. Reject booleans, non-numeric values, reversed boxes, coordinates outside `0..1`, unknown candidate roles, and candidate paths shorter than two points. Use a fixed confidence floor of `0.65`.

Extract camera intent from `camera_motion`. Extract subject intent from `subject_motion`, falling back to the matching Shot's `motion_path` and states only when the entry is empty. Preserve Master order.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/skills/storyboard_master_video_planning/test_motion_planner.py -q`

- [ ] **Step 5: Commit**

```text
git add src/ai_video_platform/skills/storyboard_master_video_planning/motion_planner.py tests/skills/storyboard_master_video_planning/test_motion_planner.py
git commit -m "feat(storyboard): validate panel visual observations"
```

### Task 2: Script and Image Reconciliation

**Files:**
- Modify: `src/ai_video_platform/skills/storyboard_master_video_planning/motion_planner.py`
- Modify: `tests/skills/storyboard_master_video_planning/test_motion_planner.py`

**Interfaces:**
- Consumes: validated objects `{id, kind, bbox}`, contacts `{actor_id, target_id, point}`, and candidates `{role, action, subject_id, points, confidence}`.
- Produces: renderer annotations `{role: "camera"|"subject", points: [[x, y], ...]}`.

- [ ] **Step 1: Write failing behavior tests**

Add exact-output tests for:

- finger press: candidate path or finger-center-to-contact path;
- two-hand squeeze: arrows from observed left/right hands toward the observed product center;
- rotate plus thumb press: two independent candidate paths;
- package entering from frame right: right-to-left path derived from the package box;
- camera push-in: two camera arrows aimed toward the observed product center;
- hold/static, missing objects, low confidence, and incompatible candidate action: empty annotations.

- [ ] **Step 2: Run tests and verify RED**

Run the motion planner test file and confirm exact path assertions fail because reconciliation is missing.

- [ ] **Step 3: Implement deterministic planners**

Prefer a compatible high-confidence visual candidate. Otherwise derive only these unambiguous paths:

- press from the matching finger/hand center to a matching contact;
- squeeze from hand box inner centers toward quarter points around product center;
- enter/exit from the observed object box and explicit script direction;
- camera push/pull from frame edges relative to the observed focal product.

Rotate without a compatible visual candidate produces no path because rotation direction is ambiguous. Hold/static produces no directional path. Sort candidates by role, script intent order, descending confidence, subject id, and points so equivalent inputs replay identically.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/skills/storyboard_master_video_planning/test_motion_planner.py -q`

- [ ] **Step 5: Commit**

```text
git add src/ai_video_platform/skills/storyboard_master_video_planning/motion_planner.py tests/skills/storyboard_master_video_planning/test_motion_planner.py
git commit -m "feat(storyboard): plan arrows from script and vision"
```

### Task 3: CLI Integration and Agent Instructions

**Files:**
- Modify: `src/ai_video_platform/skills/storyboard_master_video_planning/cli.py`
- Modify: `src/ai_video_platform/skills/storyboard_master_video_planning/__init__.py`
- Modify: `src/ai_video_platform/skills/storyboard_master_video_planning/SKILL.md`
- Modify: `tests/skills/storyboard_master_video_planning/test_video_planning_interface.py`
- Modify: `tests/skills/storyboard_master_video_planning/test_video_planning_failures.py`

**Interfaces:**
- Consumes: optional `sheet_render_metadata.panel_visual_observations`.
- Produces: generated `motion_annotations` passed only to `render_storyboard_sheets`.

- [ ] **Step 1: Write failing CLI integration tests**

Test that observations automatically generate red and blue arrow pixels without caller-supplied `motion_annotations`. Test that malformed observations return the existing `INVALID_INPUT` CLI error. Test that absent observations preserve current Provider-free rendering and do not invent arrows.

- [ ] **Step 2: Run tests and verify RED**

Run the two owned interface/failure test files and confirm the new integration assertions fail.

- [ ] **Step 3: Integrate planner**

Copy sheet metadata before enrichment. When `panel_visual_observations` is present, call `plan_motion_annotations` with the generated Master and store the result under `motion_annotations` in the copy. Convert planner `ValueError` to `PlanningError(INVALID_INPUT)` with no output of machine audit details in the PNG.

Export `plan_motion_annotations` from the skill package. Update `SKILL.md` with the mandatory Agent sequence: inspect every approved clean Panel, write structured observations, then invoke the CLI. State that the Agent must not fabricate observations from script text.

- [ ] **Step 4: Run owned tests and verify GREEN**

Run: `python -m pytest tests/skills/storyboard_master_video_planning -q`

- [ ] **Step 5: Run repository verification**

Run: `$env:PYTHONPATH='src'; python -m pytest -q`

Run: `git diff --check`

- [ ] **Step 6: Commit**

```text
git add src/ai_video_platform/skills/storyboard_master_video_planning tests/skills/storyboard_master_video_planning
git commit -m "feat(storyboard): automate vision-guided motion planning"
```

