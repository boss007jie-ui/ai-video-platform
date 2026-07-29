# Reference Analysis Fine-Segment Storyboard Increment Design

Date: 2026-07-27
Authorization: `FTG-0-20260720-001`
Work item: `FT-02-001`
Owner: `reference_analysis` / Codex-02
Branch: `ft/codex-02-research-reference`

## Goal

Extend the existing local-only Reference Analysis workflow so it first creates evidence-bound fine segments and then condenses adjacent segments into a small, readable set of core beats. The final output is an analysis storyboard for understanding a selected reference video. It is not a production storyboard, first-frame asset, image Provider input, or video Provider input.

The implementation must preserve the existing public seams:

- `prepare-reference-breakdown` prepares local media evidence and owner-local draft analysis.
- `analyze-storyboard` validates the prepared analysis, merges adjacent fine segments into core beats, and publishes the final artifact set.

No root CLI routing, shared Contract identity, other Skill, Hermes state, Provider, network service, or external upload is added or changed.

## Selected approach

Use an additive two-stage pipeline.

The preparation command remains responsible for reading one explicitly authorized workspace-relative local video. It detects fine boundaries, extracts real source frames, and records conservative segment analysis. An owner-local offline analyzer seam may add semantic signals in deterministic fixtures or authorized offline implementations. The publication command remains responsible for strict validation, adjacent-only beat merging, provenance, human-readable reporting, and board rendering.

This approach was chosen over adding a new command or making `analyze-storyboard` perform media preparation because it preserves compatibility and keeps media processing separate from artifact publication.

## Architecture and data flow

```text
selected local video
  -> prepare-reference-breakdown
     -> candidate boundary signals
     -> contiguous fine segments
     -> real keyframes from each segment
     -> evidence-bound segment analysis
     -> proposed adjacent beat groups
     -> reference_breakdown_draft/
        -> analyze_storyboard_request.json
  -> analyze-storyboard
     -> validate media, hashes, timing, evidence, and merge provenance
     -> derive core-beat sequence and bottom formula
     -> reference_analysis/
```

The preparation output is draft/intermediate data. The publication output is the final Reference Analysis result. Neither output is executable downstream media input.

## Fine segmentation

Candidate boundaries are content-driven, not fixed-count or fixed-duration buckets. The local deterministic detector combines available evidence such as:

- decoded scene-cut scores;
- frame-difference and motion-change scores;
- audio silence, onset, or section boundaries when audio exists;
- owner-local offline semantic signals for scene, shot scale, camera motion, subject action, product state, prop state, subtitle change, emotion, or attention change.

Near-duplicate boundary candidates are coalesced deterministically. The first boundary is `0`; the last boundary is the exact video duration. The resulting fine segments are ordered and contiguous, with no unexplained gap or overlap. Their count is driven by the content. A roughly 30-second video may yield approximately 10-20 segments, but no count is hard-coded.

Each record in `fine_segments.json` contains at least:

- `segment_id`;
- `source_video_id`;
- `start_ms`;
- `end_ms`;
- `duration_ms`;
- `segmentation_reasons`;
- `previous_segment_id`;
- `next_segment_id`.

Every segmentation reason carries evidence describing the detected boundary signal. Missing semantic capability is represented explicitly and never replaced with invented facts.

## Real keyframes

Every fine segment receives real frames decoded from the selected source video:

- `start`;
- `representative`;
- `end`.

Evidence may add `action_peak`, `product_state_change`, or `subtitle_change` frames. Timestamps must fall inside their owning segment. The end role uses the last decodable instant inside the interval so a frame never leaks into the next segment.

Every keyframe index record contains:

- `frame_id`;
- `source_video_id`;
- `segment_id`;
- `timestamp_ms`;
- `frame_role`;
- `asset_path`;
- `sha256`.

Generated images are forbidden. Publication re-verifies the file digest and interval ownership before copying the frame into the final `keyframes/` directory.

## Segment analysis

`segment_analysis.json` records every fine segment. Its observations cover:

- scene;
- shot scale and camera position;
- camera motion;
- subject motion;
- character, hand, or primary-subject action;
- product action and product state;
- package, container, and prop state;
- subtitle and visible text;
- speech, music, and sound-effect function;
- emotion change;
- attention target;
- audience psychology;
- narrative function;
- viral mechanism;
- commercial or conversion function.

Each non-`UNAVAILABLE` observation cites one or more allowed evidence references: source media, an in-segment keyframe, an audio interval, or an available comment record. The validator rejects unknown evidence, cross-segment frame evidence, or claims that cannot be traced to the selected video.

## Core-beat merging

Only adjacent fine segments may be merged. The merge decision considers shared narrative purpose, audience psychology, viral/conversion function, complete action, product-state stage, and continuity of people, scene, and event.

Each core beat records:

- `beat_id`;
- `source_segment_ids`;
- `source_frame_ids`;
- `start_ms`;
- `end_ms`;
- `representative_frame_id`;
- `merge_reason`;
- concise title, visual/action summary, audience psychology, and function label.

The typical final board contains 5-9 beats, but the implementation does not force an incorrect count. It rejects non-contiguous source groups and any representative frame not owned by the merged interval.

The bottom formula is generated from the ordered, confirmed beat titles/functions. It is not accepted as an unrelated free-form summary.

## Final outputs

`analyze-storyboard` atomically publishes beneath `reference_analysis/`:

```text
reference_analysis/
  fine_segments.json
  keyframes/
  segment_analysis.json
  reference_storyboard_analysis.json
  reference_storyboard_analysis.md
  reference_storyboard_analysis_board.png
  analysis_provenance.json
```

Existing formal Reference Analysis artifact identities remain unchanged and are reused. Fine-segment details are owner-local structures within the existing Reference Storyboard Analysis publication. No synonymous Business Artifact or shared Contract is introduced.

`analysis_provenance.json` links the selected media digest, segment intervals, keyframe IDs and hashes, analysis evidence, merge groups, board asset, request digest, and local method provenance. It records:

- `network_calls: 0`;
- `provider_calls: 0`;
- `external_upload: false`.

## Board design

`reference_storyboard_analysis_board.png` uses a black background with orange accents and a horizontal sequence of limited core-beat cards.

The header displays:

- `分镜故事板 / Storyboard`;
- topic/category;
- platform;
- aspect ratio;
- exact total duration.

Each card displays a real representative frame, stage number, exact interval, concise title, visual or scene summary, key action, audience psychology, viral/conversion role, and short function tag. Machine-oriented evidence lists and full segment observations stay in JSON and Markdown.

The footer displays the formula derived from the ordered confirmed beats. PNG metadata retains the full board manifest, source restrictions, and non-executable role flags.

The first generated sample is a review candidate. Visual styling is not declared final until the user reviews it.

## Failure behavior

The workflow fails closed on:

- missing or changed source media;
- unavailable required local media tools;
- absolute, traversal, link, or reparse-point paths;
- keyframe digest mismatch or timestamp outside its segment;
- timeline gaps, overlaps, reversed intervals, or duration mismatch;
- non-adjacent or incomplete merge groups;
- evidence references outside the selected source and interval;
- invented semantic claims where evidence is unavailable;
- production, first-frame, panel, or Provider execution roles;
- output collisions with non-identical content.

Publication remains atomic and deterministic. Identical replay is idempotent.

## Testing strategy

Tests exercise only the two approved public seams and proceed in vertical red-green slices.

### `prepare-reference-breakdown`

- A local synthetic video produces content-driven contiguous fine segments.
- Every segment has required adjacency and timing fields.
- Every segment has real start, representative, and end frames with valid hashes and timestamps.
- Segment analysis carries the required observation categories and evidence references.
- Network, Provider, and upload counters remain zero/false.

### `analyze-storyboard`

- Fine segments are validated before any merge or publication.
- Adjacent compatible segments become a limited set of traceable core beats.
- The formula equals the ordered confirmed beat progression.
- The exact required artifact set is published atomically.
- The board uses only source-video frames and advertises no executable role.

### Boundary and regression checks

- Tampered frames, gaps, overlaps, cross-segment evidence, and invalid merge groups fail with stable errors.
- Existing Reference Analysis public calls remain compatible.
- Owned tests and affected offline/architecture tests pass.
- The diff contains no changes to `storyboard_master_video_planning`, root CLI, other Skills, shared Contracts, or Hermes state.

## Sample and stopping condition

Use an authorized local or versioned synthetic reference video to generate one complete sample artifact set and the first `reference_storyboard_analysis_board.png`. After fresh owned/affected verification and an implementation commit, report the commit SHA, changed files, artifact paths, network/Provider counters, and blockers. Then stop and wait for user feedback on the image.
