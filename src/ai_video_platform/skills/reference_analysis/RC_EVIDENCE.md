# Reference Analysis - Fine Storyboard Offline Evidence

## Identity and status

- Authorization: `FTG-0-20260720-001`
- Work item: `FT-02-001`
- Branch: `ft/codex-02-research-reference`
- Implementation evidence head: `89e69fc`
- Schema/algorithm version: `1.0.0`
- Status: `FIRST_SAMPLE_REVIEW`
- Visual final: **not claimed**
- Provenance: `CLEAN_ROOM_ONLY`; no Legacy source, Provider, upload, or network service was used

The increment preserves the public `prepare-reference-breakdown` and `analyze-storyboard` seams. The additive `local_fine_segments_v1` flow accepts an explicitly selected workspace-relative local video, detects content-driven boundaries, extracts source frames, builds evidence-bound segment analysis, merges adjacent semantically equivalent segments, and publishes a compact Reference Storyboard Analysis Board. Legacy `local_draft_v1` behavior remains available.

## Implemented offline behavior

- content-driven visual/audio boundary detection with deterministic offline semantic signals;
- ordered, contiguous fine segments with exact previous/next links and segmentation reasons;
- real start, representative, and end frames per segment, each bound to source video, interval, role, path, and SHA-256;
- fifteen evidence-bearing analysis categories per fine segment, with unsupported claims represented as `UNAVAILABLE`;
- adjacent-only semantic merging with exact source segment/frame provenance;
- a formula derived from the confirmed ordered core beats;
- atomic publication of `fine_segments.json`, `keyframes/`, `segment_analysis.json`, `reference_storyboard_analysis.json`, `reference_storyboard_analysis.md`, `reference_storyboard_analysis_board.png`, and `analysis_provenance.json`;
- a 3000 x 1500 black/orange horizontal board using source-video representative frames and five core-beat cards in the review fixture;
- strict local-media execution limited to resolved `ffmpeg`/`ffprobe`, with URL/protocol arguments rejected and generic subprocess escapes still denied by the shared offline guard;
- unchanged formal Reference Analysis artifact identities and no production-storyboard or Provider-execution role.

## Fresh verification at implementation evidence head

| Command | Result |
|---|---|
| `$env:PYTHONPATH='src'; python -m unittest discover -s tests/skills/reference_analysis -t . -p "test_*.py" -v` | PASS - 37 run, 36 passed, 1 host-capability skip, 0 failures, 89.171s |
| Fine local-media integration plus shared subprocess escape under `NetworkDenyGuard` | PASS - 2/2 |
| `python tools/run_offline_tests.py` | AFFECTED SUITE - 583 run, 579 passed, 3 skips, 1 shared environment-path error, 94.978s |
| `git diff --check` and owner-scope diff inspection | PASS |

The owned skip is the existing Windows environment case where symlink creation is unavailable. The only complete-suite error is `architecture.test_clean_room_boundaries.CleanRoomBoundaryTests.test_adoption_manifest_has_no_unapproved_adoptions`: the shared test derives the control root as a sibling of the current Git worktree and therefore looks for `C:\Users\boss0\.codex\worktrees\9352\AI Video Platform Re-architecture Control\08_ADOPTION_MANIFEST.json`, which does not exist in this Codex-managed worktree layout. That shared architecture test is outside the authorized `reference_analysis` scope and was not modified.

## First review sample

- Root: `run/FT-02-001-reference-storyboard-increment-review-03/reference_analysis/`
- Source fixture: versioned synthetic local video, 4000 ms
- Fine segments: 10
- Source keyframes: 30
- Core beats: 5
- Board: `reference_storyboard_analysis_board.png`, 3000 x 1500
- Counters: `network_calls=0`, `provider_calls=0`, `external_upload=false`

The board was visually inspected for layout, Chinese title rendering, source-frame placement, five-card readability, and formula arrows. It remains a first review candidate pending user feedback.

## Scope and open gate

All committed changes from the increment baseline are limited to `src/ai_video_platform/skills/reference_analysis/**` and `tests/skills/reference_analysis/**`. No change was made to `storyboard_master_video_planning`, the root CLI dispatcher, other Skills, shared Contracts, or Hermes state.

The current stop gate is user visual review of the first sample. Branch integration is intentionally deferred until that feedback is received. The unrelated shared worktree-path test remains an external verification blocker.
