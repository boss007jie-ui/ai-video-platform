# Reference Analysis Fine-Segment Storyboard Increment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing local Reference Analysis workflow to create evidence-bound fine segments, real multi-role keyframes, segment analyses, traceable core beats, and a compact black/orange analysis storyboard.

**Architecture:** Preserve `prepare-reference-breakdown` as the local media-processing seam and `analyze-storyboard` as the strict publication seam. Add focused owner-local modules for content-driven segmentation and fine-segment/beat derivation, while retaining legacy `local_draft_v1` behavior and adding `local_fine_segments_v1` for the new workflow.

**Tech Stack:** Python 3.12+, standard library, local `ffmpeg`/`ffprobe`, existing dependency-free PNG renderer, `unittest`, synthetic/offline fixtures.

## Global Constraints

- Authorization is `FTG-0-20260720-001`; work item is `FT-02-001`.
- Modify only `src/ai_video_platform/skills/reference_analysis/**`, `tests/skills/reference_analysis/**`, and ignored local sample output under `run/**`.
- Do not modify `storyboard_master_video_planning`, root CLI, any other Skill, shared Contracts, or Hermes state.
- Do not call Apify, image Providers, video Providers, network services, or upload services.
- Reuse the existing Reference Analysis artifact identities; do not add a synonymous Business Artifact or shared Contract.
- All keyframes must be decoded from the selected source video and verified by timestamp and SHA-256.
- The final formula must be derived from the ordered confirmed core beats.
- Preserve `local_draft_v1`; the increment uses `mode=local_fine_segments_v1` through the existing command.
- Generated media stays out of Git; the review sample is written beneath ignored `run/`.

---

## File structure

- Create `src/ai_video_platform/skills/reference_analysis/fine_segments.py`: local visual/audio boundary detection, boundary coalescing, and contiguous fine-segment construction.
- Create `src/ai_video_platform/skills/reference_analysis/segment_storyboard.py`: offline annotation normalization, evidence-bound segment analysis, adjacent core-beat grouping, and formula derivation.
- Modify `src/ai_video_platform/skills/reference_analysis/draft.py`: dispatch legacy/new modes, extract multi-role source frames, and publish the expanded draft package.
- Modify `src/ai_video_platform/skills/reference_analysis/storyboard.py`: validate owner-local fine data and publish the required final files without changing formal artifact identities.
- Modify `src/ai_video_platform/skills/reference_analysis/storyboard_boards.py`: render the compact horizontal black/orange board.
- Modify `src/ai_video_platform/skills/reference_analysis/SKILL.md`: document the new mode, artifacts, restrictions, and counters.
- Create `tests/skills/reference_analysis/test_fine_segment_preparation.py`: public-seam preparation behavior.
- Create `tests/skills/reference_analysis/test_fine_segment_publication.py`: public-seam publication behavior and provenance.
- Create `tests/skills/reference_analysis/test_fine_segment_failures.py`: fail-closed timing, evidence, and merge validation.
- Create `tests/skills/reference_analysis/fine_segment_fixture.py`: deterministic local fixture request/annotation builder shared only by owner tests.

---

### Task 1: Content-driven contiguous fine segments

**Files:**
- Create: `src/ai_video_platform/skills/reference_analysis/fine_segments.py`
- Modify: `src/ai_video_platform/skills/reference_analysis/draft.py`
- Create: `tests/skills/reference_analysis/fine_segment_fixture.py`
- Create: `tests/skills/reference_analysis/test_fine_segment_preparation.py`

**Interfaces:**
- Consumes: `prepare_reference_breakdown(request: Mapping[str, object], *, workspace: Path) -> ReferenceBreakdownDraftResult`.
- Produces: `detect_boundary_signals(media: Path, duration_ms: int, policy: Mapping[str, object]) -> list[dict[str, object]]` and `build_fine_segments(source_video_id: str, duration_ms: int, signals: Sequence[Mapping[str, object]], min_segment_ms: int) -> list[dict[str, object]]`.

- [ ] **Step 1: Add a public-seam failing test for fine segmentation**

```python
def test_prepare_fine_mode_creates_contiguous_content_driven_segments(self) -> None:
    request = fine_segment_request(media_sha256, boundaries=(400, 800, 1200, 1600, 2000, 2400, 2800, 3200, 3600))
    result = prepare_reference_breakdown(request, workspace=workspace)
    segments = json.loads((workspace / result.output_root / "fine_segments.json").read_text("utf-8"))
    self.assertEqual(len(segments), 10)
    self.assertEqual(segments[0]["start_ms"], 0)
    self.assertEqual(segments[-1]["end_ms"], 4000)
    self.assertTrue(all(left["end_ms"] == right["start_ms"] for left, right in zip(segments, segments[1:])))
    self.assertTrue(all(segment["segmentation_reasons"] for segment in segments[1:]))
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_preparation.PrepareFineSegmentTests.test_prepare_fine_mode_creates_contiguous_content_driven_segments -v`

Expected: FAIL because `local_fine_segments_v1` and `fine_segments.json` are not implemented.

- [ ] **Step 3: Implement deterministic signal detection and segment construction**

Implement `fine_segments.py` with:

```python
def detect_boundary_signals(media: Path, duration_ms: int, policy: Mapping[str, object]) -> list[dict[str, object]]:
    """Return ordered local visual/audio boundary evidence without network access."""

def build_fine_segments(
    source_video_id: str,
    duration_ms: int,
    signals: Sequence[Mapping[str, object]],
    min_segment_ms: int,
) -> list[dict[str, object]]:
    """Coalesce nearby signals and return an exact contiguous source timeline."""
```

Decode low-resolution RGB samples with local `ffmpeg` and compute mean absolute frame differences. Parse local `silencedetect` output when an audio stream exists. Merge optional `offline_analysis.boundary_signals` with local signals. Coalesce candidates less than `min_segment_ms` apart, preserve all reasons on the winning boundary, and create deterministic `segment-001` IDs with previous/next links.

- [ ] **Step 4: Extend `draft.py` request dispatch minimally**

Accept `mode=local_fine_segments_v1` with owner-local fields:

```python
_FINE_MODE = "local_fine_segments_v1"
_FINE_ALLOWED = _REQUEST_REQUIRED | {
    "video_metadata", "current_product", "segmentation_policy", "offline_analysis"
}
```

For this slice, publish `fine_segments.json` in the draft root while leaving legacy `local_draft_v1` output unchanged.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_preparation.PrepareFineSegmentTests.test_prepare_fine_mode_creates_contiguous_content_driven_segments -v`

Expected: PASS.

- [ ] **Step 6: Run legacy preparation tests**

Run: `python -m unittest tests.skills.reference_analysis.test_prepare_reference_breakdown tests.skills.reference_analysis.test_prepare_reference_breakdown_failures -v`

Expected: PASS with unchanged `local_draft_v1` behavior.

- [ ] **Step 7: Commit the slice**

```powershell
git add src/ai_video_platform/skills/reference_analysis/fine_segments.py src/ai_video_platform/skills/reference_analysis/draft.py tests/skills/reference_analysis/fine_segment_fixture.py tests/skills/reference_analysis/test_fine_segment_preparation.py
git commit -m "feat(reference-analysis): detect fine video segments"
```

---

### Task 2: Real multi-role keyframes and segment analysis

**Files:**
- Create: `src/ai_video_platform/skills/reference_analysis/segment_storyboard.py`
- Modify: `src/ai_video_platform/skills/reference_analysis/draft.py`
- Modify: `tests/skills/reference_analysis/fine_segment_fixture.py`
- Modify: `tests/skills/reference_analysis/test_fine_segment_preparation.py`

**Interfaces:**
- Consumes: fine segments from `build_fine_segments` and optional `offline_analysis.segment_annotations` keyed by exact `start_ms`/`end_ms`.
- Produces: `build_segment_analysis(segments, keyframes, annotations) -> list[dict[str, object]]` and draft `keyframes/index.json`, `segment_analysis.json`.

- [ ] **Step 1: Add a failing test for source-frame roles and evidence**

```python
def test_every_fine_segment_has_real_start_representative_and_end_frames(self) -> None:
    root = prepare_fine_fixture(workspace)
    segments = load_json(root / "fine_segments.json")
    frames = load_json(root / "keyframes" / "index.json")
    analyses = load_json(root / "segment_analysis.json")
    for segment in segments:
        owned = [frame for frame in frames if frame["segment_id"] == segment["segment_id"]]
        self.assertEqual({frame["frame_role"] for frame in owned}, {"start", "representative", "end"})
        self.assertTrue(all(segment["start_ms"] <= frame["timestamp_ms"] < segment["end_ms"] for frame in owned))
        self.assertTrue(all(len(frame["sha256"]) == 64 for frame in owned))
    self.assertEqual({item["segment_id"] for item in analyses}, {item["segment_id"] for item in segments})
    self.assertTrue(all(len(item["observations"]) == 15 for item in analyses))
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_preparation.PrepareFineSegmentTests.test_every_fine_segment_has_real_start_representative_and_end_frames -v`

Expected: FAIL because multi-role frames and `segment_analysis.json` are absent.

- [ ] **Step 3: Extract three real frames per fine segment**

For each half-open segment `[start_ms, end_ms)`, calculate:

```python
start_timestamp = start_ms
representative_timestamp = start_ms + (duration_ms // 2)
end_timestamp = end_ms - 1
```

Call the existing local `_extract_keyframe` for each role, hash the exact PNG bytes, and record:

```python
{
    "frame_id": "segment-001-start",
    "source_video_id": source_id,
    "segment_id": "segment-001",
    "timestamp_ms": 0,
    "frame_role": "start",
    "asset_path": "reference_breakdown_draft/keyframes/segment-001-start.png",
    "sha256": digest,
}
```

- [ ] **Step 4: Normalize the 15 evidence-bound observations**

Implement in `segment_storyboard.py`:

```python
OBSERVATION_FIELDS = (
    "scene", "shot_scale_and_camera_position", "camera_motion", "subject_motion",
    "primary_subject_action", "product_action_and_state", "package_container_prop_state",
    "subtitle_and_visible_text", "speech_music_sound_effect", "emotion_change",
    "attention_target", "audience_psychology", "narrative_function",
    "viral_mechanism", "conversion_function",
)

def build_segment_analysis(
    segments: Sequence[Mapping[str, object]],
    keyframes: Sequence[Mapping[str, object]],
    annotations: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    ...
```

Require annotations to match exact segment intervals. Bind each supplied value to real in-segment frame evidence. Emit `UNAVAILABLE` with an empty evidence list for unsupplied semantics. Record annotation provenance as offline/local and never reinterpret missing values.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_preparation -v`

Expected: PASS.

- [ ] **Step 6: Commit the slice**

```powershell
git add src/ai_video_platform/skills/reference_analysis/segment_storyboard.py src/ai_video_platform/skills/reference_analysis/draft.py tests/skills/reference_analysis/fine_segment_fixture.py tests/skills/reference_analysis/test_fine_segment_preparation.py
git commit -m "feat(reference-analysis): extract segment evidence frames"
```

---

### Task 3: Adjacent core-beat derivation and prepared request

**Files:**
- Modify: `src/ai_video_platform/skills/reference_analysis/segment_storyboard.py`
- Modify: `src/ai_video_platform/skills/reference_analysis/draft.py`
- Modify: `tests/skills/reference_analysis/test_fine_segment_preparation.py`

**Interfaces:**
- Consumes: normalized segment analyses and keyframe index.
- Produces: `derive_core_beats(segments, analyses, keyframes) -> list[dict[str, object]]`, `derive_formula(beats) -> dict[str, object]`, and a request directly consumable by `analyze_storyboard`.

- [ ] **Step 1: Add a failing public-seam test for fine-first/merge-second behavior**

```python
def test_preparation_merges_only_adjacent_semantically_matching_segments(self) -> None:
    root = prepare_fine_fixture(workspace, ten_segments_in_five_semantic_pairs=True)
    request = load_json(root / "analyze_storyboard_request.json")
    self.assertEqual(len(request["analysis_configuration"]["fine_segments"]), 10)
    beats = request["analysis_configuration"]["core_beats"]
    self.assertEqual(len(beats), 5)
    self.assertEqual(beats[0]["source_segment_ids"], ["segment-001", "segment-002"])
    self.assertEqual(
        request["analysis_configuration"]["bottom_line_formula"]["value"],
        "Problem Hook -> Product Reveal -> Use Demo -> Result Proof -> Natural Close",
    )
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_preparation.PrepareFineSegmentTests.test_preparation_merges_only_adjacent_semantically_matching_segments -v`

Expected: FAIL because `core_beats` are absent.

- [ ] **Step 3: Implement adjacent-only merge derivation**

```python
def derive_core_beats(
    segments: Sequence[Mapping[str, object]],
    analyses: Sequence[Mapping[str, object]],
    keyframes: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Merge only adjacent segments sharing narrative/psychology/mechanism/action/state purpose."""

def derive_formula(beats: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "value": " -> ".join(str(beat["stage_title"]) for beat in beats),
        "source_beat_ids": [beat["beat_id"] for beat in beats],
        "evidence_refs": [f"beat:{beat['beat_id']}" for beat in beats],
    }
```

The merge signature uses normalized `narrative_function`, `audience_psychology`, `viral_mechanism`, `conversion_function`, `primary_subject_action`, and `product_action_and_state`. Merge only consecutive equal available signatures. If no semantic match is available, keep the content-driven segment separate; do not force a target count.

- [ ] **Step 4: Generate the new-mode publication request**

Add owner-local `fine_segments`, `segment_analysis`, and `core_beats` fields under `analysis_configuration`. Map core beats into the existing timeline observation fields for compatibility, use each beat's `representative_frame_id` as the board image, and include every extracted keyframe in the request.

- [ ] **Step 5: Run the preparation test file and verify GREEN**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_preparation -v`

Expected: PASS.

- [ ] **Step 6: Commit the slice**

```powershell
git add src/ai_video_platform/skills/reference_analysis/segment_storyboard.py src/ai_video_platform/skills/reference_analysis/draft.py tests/skills/reference_analysis/test_fine_segment_preparation.py
git commit -m "feat(reference-analysis): derive traceable core beats"
```

---

### Task 4: Strict publication of fine artifacts and provenance

**Files:**
- Modify: `src/ai_video_platform/skills/reference_analysis/storyboard.py`
- Create: `tests/skills/reference_analysis/test_fine_segment_publication.py`
- Create: `tests/skills/reference_analysis/test_fine_segment_failures.py`

**Interfaces:**
- Consumes: existing `analyze_storyboard` request plus the optional owner-local trio `fine_segments`, `segment_analysis`, `core_beats`.
- Produces: the exact seven-part `reference_analysis/` artifact set and extended provenance counters.

- [ ] **Step 1: Add a failing end-to-end publication test**

```python
def test_analyze_storyboard_publishes_fine_artifacts_and_traceable_core_beats(self) -> None:
    prepared_request = prepare_fine_fixture(workspace)
    result = analyze_storyboard(prepared_request, workspace=workspace)
    root = workspace / result.output_root
    expected = {
        "fine_segments.json", "segment_analysis.json",
        "reference_storyboard_analysis.json", "reference_storyboard_analysis.md",
        "reference_storyboard_analysis_board.png", "analysis_provenance.json",
    }
    self.assertTrue(expected.issubset({path.name for path in root.iterdir()}))
    artifact = load_json(root / "reference_storyboard_analysis.json")
    self.assertEqual(len(artifact["fine_segments"]), 10)
    self.assertEqual(len(artifact["reference_beats"]), 5)
    self.assertEqual(artifact["reference_beats"][0]["source_segment_ids"], ["segment-001", "segment-002"])
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_publication.FineSegmentPublicationTests.test_analyze_storyboard_publishes_fine_artifacts_and_traceable_core_beats -v`

Expected: FAIL because strict configuration rejects owner-local fine fields.

- [ ] **Step 3: Validate fine segments, analyses, and core beats**

Extend configuration validation without changing `_CONTRACTS`. Require exact segment coverage, adjacency links, unique IDs, duration equality, complete analysis coverage, in-segment evidence, adjacent complete beat partitions, representative-frame ownership, and source frame hashes.

Keep the legacy request path valid when all three owner-local fields are absent. Reject partial presence of the trio.

- [ ] **Step 4: Publish the required files and counters**

Add to the final artifact and files map:

```python
artifact["fine_segments"] = fine_segments
artifact["segment_analysis"] = segment_analysis
artifact["reference_beats"] = core_beats
files["fine_segments.json"] = _pretty(fine_segments)
files["segment_analysis.json"] = _pretty(segment_analysis)
```

Extend provenance with segment/frame/beat trace records plus `network_calls=0`, `provider_calls=0`, and `external_upload=False`.

- [ ] **Step 5: Add and run fail-closed tests**

Cover: one-millisecond gap, overlap, bad previous/next IDs, frame timestamp outside segment, tampered SHA, unknown evidence, missing segment analysis, non-adjacent merge, incomplete merge partition, and representative frame outside a beat.

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_failures -v`

Expected: all cases raise a stable `SkillError` and publish no `reference_analysis/` directory.

- [ ] **Step 6: Run all publication tests and verify GREEN**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_publication tests.skills.reference_analysis.test_storyboard_analysis tests.skills.reference_analysis.test_storyboard_analysis_failures -v`

Expected: PASS for both new and legacy publication requests.

- [ ] **Step 7: Commit the slice**

```powershell
git add src/ai_video_platform/skills/reference_analysis/storyboard.py tests/skills/reference_analysis/test_fine_segment_publication.py tests/skills/reference_analysis/test_fine_segment_failures.py
git commit -m "feat(reference-analysis): publish fine storyboard evidence"
```

---

### Task 5: Compact black/orange horizontal board

**Files:**
- Modify: `src/ai_video_platform/skills/reference_analysis/storyboard_boards.py`
- Modify: `tests/skills/reference_analysis/test_fine_segment_publication.py`

**Interfaces:**
- Consumes: validated core beats, decoded representative source frames, selected source metadata, and derived formula.
- Produces: deterministic `reference_storyboard_analysis_board.png` with embedded `avp-layout` metadata.

- [ ] **Step 1: Add a failing renderer behavior test through `analyze_storyboard`**

```python
def test_board_is_compact_horizontal_and_uses_only_core_representative_frames(self) -> None:
    root = publish_fine_fixture(workspace)
    metadata = png_text_chunks((root / "reference_storyboard_analysis_board.png").read_bytes())
    layout = json.loads(metadata["avp-layout"])
    self.assertEqual(layout["title"], "分镜故事板 / Storyboard")
    self.assertEqual(layout["theme"], "black-orange")
    self.assertEqual(layout["layout"], "horizontal-core-beat-cards")
    self.assertEqual(len(layout["beats"]), 5)
    self.assertEqual(
        [beat["representative_frame_id"] for beat in layout["beats"]],
        ["segment-001-representative", "segment-003-representative", "segment-005-representative", "segment-007-representative", "segment-009-representative"],
    )
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_publication.FineSegmentPublicationTests.test_board_is_compact_horizontal_and_uses_only_core_representative_frames -v`

Expected: FAIL because the existing board is vertical and light-themed.

- [ ] **Step 3: Implement the compact board renderer**

Render a black `3000x1500` canvas with orange accents, a bilingual title, metadata row, 5-9 horizontal cards, real representative frames, concise card copy, and a footer formula. Add only the small embedded glyphs needed for the fixed Chinese title so no new runtime dependency is introduced. For legacy requests, keep a compatible fallback using existing beat fields.

Embed metadata:

```python
{
    "board_role": "reference_storyboard_analysis_board",
    "title": "分镜故事板 / Storyboard",
    "theme": "black-orange",
    "layout": "horizontal-core-beat-cards",
    "beats": core_beats,
    "bottom_line_formula": formula,
    "provider_execution_input": False,
    "first_frame_eligible": False,
    "product_panel_eligible": False,
}
```

- [ ] **Step 4: Run focused and legacy renderer tests**

Run: `python -m unittest tests.skills.reference_analysis.test_fine_segment_publication tests.skills.reference_analysis.test_storyboard_analysis -v`

Expected: PASS.

- [ ] **Step 5: Commit the slice**

```powershell
git add src/ai_video_platform/skills/reference_analysis/storyboard_boards.py tests/skills/reference_analysis/test_fine_segment_publication.py
git commit -m "feat(reference-analysis): render compact analysis storyboard"
```

---

### Task 6: Skill documentation, sample, and full verification

**Files:**
- Modify: `src/ai_video_platform/skills/reference_analysis/SKILL.md`
- Modify: `src/ai_video_platform/skills/reference_analysis/RC_EVIDENCE.md`
- Generate ignored: `run/FT-02-001-reference-storyboard-increment/reference_analysis/**`

**Interfaces:**
- Consumes: the complete `prepare-reference-breakdown` -> `analyze-storyboard` workflow.
- Produces: one review sample, fresh verification evidence, and the final implementation commit.

- [ ] **Step 1: Update owner documentation**

Document `local_fine_segments_v1`, the two-stage flow, the seven required outputs, exact source-frame and evidence rules, adjacent merge semantics, black/orange board, non-production restrictions, and zero counters. Do not describe the first sample as visually final.

- [ ] **Step 2: Run the complete owner test suite**

Run: `python -m unittest discover -s tests/skills/reference_analysis -p "test_*.py" -v`

Expected: PASS with zero failures; a Windows symlink test may skip only when OS permissions deny symlink creation.

- [ ] **Step 3: Run affected offline and architecture tests**

Run: `python tools/run_offline_tests.py`

Expected: PASS with zero failures.

- [ ] **Step 4: Generate the first local review sample**

Create `run/FT-02-001-reference-storyboard-increment/inputs/reference.mp4` from the authorized synthetic fixture, run:

```powershell
python -m ai_video_platform.skills.reference_analysis prepare-reference-breakdown --input run/FT-02-001-reference-storyboard-increment/prepare.json --workspace run/FT-02-001-reference-storyboard-increment
python -m ai_video_platform.skills.reference_analysis analyze-storyboard --input run/FT-02-001-reference-storyboard-increment/reference_breakdown_draft/analyze_storyboard_request.json --workspace run/FT-02-001-reference-storyboard-increment
```

Confirm the final directory contains `fine_segments.json`, `keyframes/`, `segment_analysis.json`, `reference_storyboard_analysis.json`, `reference_storyboard_analysis.md`, `reference_storyboard_analysis_board.png`, and `analysis_provenance.json`.

- [ ] **Step 5: Inspect the sample board and provenance**

Open the PNG locally, confirm exactly five core cards use source-video frames, and confirm the footer matches the ordered beats. Read provenance and confirm `network_calls=0`, `provider_calls=0`, and `external_upload=false`.

- [ ] **Step 6: Verify scope and working tree**

Run:

```powershell
git diff --name-only 83f2409..HEAD
git status --short
git diff --check
```

Expected: only `reference_analysis` owner source/tests/docs are tracked changes; ignored `run/` sample is absent from Git status; no whitespace errors.

- [ ] **Step 7: Commit documentation and final evidence**

```powershell
git add src/ai_video_platform/skills/reference_analysis/SKILL.md src/ai_video_platform/skills/reference_analysis/RC_EVIDENCE.md
git commit -m "docs(reference-analysis): document fine storyboard workflow"
```

- [ ] **Step 8: Stop for user image review**

Report the final implementation SHA, changed file list, sample artifact paths, owned/affected test results, zero counters, and blockers. Display `reference_storyboard_analysis_board.png` and explicitly state that visual styling is awaiting user feedback rather than final.
