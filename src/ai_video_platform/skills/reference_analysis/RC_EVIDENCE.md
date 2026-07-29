# Reference Analysis - Replication Blueprint Offline Evidence

## Identity and status

- Authorization: `FTG-0-20260720-001`
- Work item: `FT-02-001`
- Branch: `ft/codex-02-research-reference`
- Implementation baseline: `e1e3141`
- Schema/algorithm version: `1.0.0`
- Skill version: `0.3.0-rc.offline`
- Status: `OFFLINE_ACCEPTANCE`
- Visual final: **not claimed**
- Provenance: `CLEAN_ROOM_ONLY`; no Legacy source, Provider, upload, or network service was used

The increment preserves the public `prepare-reference-breakdown` and `analyze-storyboard` seams.
The existing `local_fine_segments_v1` flow now supports motion, narrative, and hybrid replication
profiles while retaining legacy `local_draft_v1` behavior and all formal Contract identities.

## Implemented offline behavior

- explicit `MOTION_REPLICATION`, `NARRATIVE_REPLICATION`, and `HYBRID_REPLICATION` profiles with Hybrid as the default;
- content-driven fine segments carrying exact shot/scene ownership and real source-video frames;
- profile-specific semantic keyframes deduplicated by `(segment_id, timestamp_ms)` with independent action and narrative roles;
- evidenced motion state chains, contact states, adjacent motion transitions, and one bounded Motion Coverage supplementation pass;
- verified facts, grouped events, causal edges, global story roles, repeated product-proof loops, and one bounded Narrative Coverage pass;
- scene/blocking maps plus `MUST_PRESERVE`, `REPLACEABLE`, and `CONDITIONALLY_REPLACEABLE` constraints;
- owner-local `ReferenceBlueprint` with `formal_contract_identity=null` and a shared keyframe timeline;
- publication-time validation of profile/source ownership, semantic roles, transition/event references, coverage additions, and blueprint consistency;
- publication-time re-decoding of every keyframe from the SHA-verified selected local video;
- a finite core-Beat storyboard plus a separate source-frame motion atlas grouped by action;
- atomic publication of all replication JSON, PNG, keyframe, storyboard, and provenance files;
- unchanged production-storyboard and Provider-execution boundaries with zero external counters.

## Fresh verification

| Command | Result |
|---|---|
| `$env:PYTHONPATH='src'; python -m py_compile ...; python -m unittest discover -s tests/skills/reference_analysis -t . -p "test_*.py" -v` | PASS - 51 passed, 1 host-capability skip, 0 failures, 311.819s |
| `python -m unittest tests.contracts.test_storyboard_artifact_chain tests.contracts.test_root_cli_routing tests.architecture.test_clean_room_boundaries -v` | 19 passed; 1 known external worktree-path error |
| Offline CLI prepare plus analyze E2E | PASS - `HYBRID_REPLICATION`, completed locally |
| Visual inspection of storyboard and motion atlas | PASS - no overlap; labels, timecodes, directions, and action ordering readable |
| `git diff --check` and owner-scope inspection | PASS |

The owned skip is the existing Windows environment case where symlink creation is unavailable.
The affected-suite error is also pre-existing: `test_adoption_manifest_has_no_unapproved_adoptions`
derives the control root as a sibling of the current Git worktree and looks for
`C:\Users\boss0\.codex\worktrees\9352\AI Video Platform Re-architecture Control\08_ADOPTION_MANIFEST.json`,
which does not exist in this Codex-managed worktree layout. The shared architecture test is
outside the authorized `reference_analysis` scope and was not modified.

## Offline review sample

- Root: `run/FT-02-001-reference-analysis-replication/reference_analysis/`
- Source fixture: versioned synthetic local video, 4000 ms
- Profile: `HYBRID_REPLICATION`
- Fine segments: 10
- Deduplicated source keyframes: 47
- Core beats: 5
- Motion actions/transitions: 3 / 14
- Narrative facts/events/causal edges/proof loops: 10 / 5 / 4 / 2
- Coverage additions: 7 motion frames, 4 narrative frames
- Counters: `network_calls=0`, `provider_calls=0`, `external_upload=false`

The synthetic fixture contains simple red/blue source frames and exists to verify deterministic
timing, source re-decoding, layouts, and cross-artifact traceability. It is not represented as a
real garment analysis. The storyboard and atlas remain review candidates pending a rerun with an
authorized real reference video.

## Scope and blockers

All tracked changes remain limited to `src/ai_video_platform/skills/reference_analysis/**` and
`tests/skills/reference_analysis/**`. No change was made to `storyboard_master_video_planning`,
the root CLI dispatcher, other Skills, shared Contracts, Hermes state, or Provider authorization.

Implementation blocker: none. Real-video acceptance awaits an authorized local input asset and
does not block the offline implementation.
