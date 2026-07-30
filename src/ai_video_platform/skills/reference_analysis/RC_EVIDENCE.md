# Reference Analysis - Replication Blueprint Offline Evidence

## Identity and status

- Authorization: `FTG-0-20260720-001`
- Work item: `FT-02-001`
- Branch: `ft/codex-00-integration`
- Implementation baseline: `dc6865a`
- Schema/algorithm version: `1.0.0`
- Skill version: `0.4.1-rc.offline`
- Status: `OFFLINE_VERIFIED`
- Visual final: **not claimed**
- Provenance: `CLEAN_ROOM_ONLY`; no Legacy source, Provider, upload, or network service was used

The increment preserves `prepare-reference-breakdown`, adds the preferred
`finalize-reference-analysis` name while keeping `analyze-storyboard` as an owner-local alias,
and leaves all formal Contract identities unchanged.

## Implemented offline behavior

- mandatory user-supplied Analysis Brief; no silent focus or Hybrid selection;
- fixed two-question Agent interaction that asks replication target before inference policy and forbids precomposed bundles;
- deterministic mappings for motion-only, narrative-only, hybrid, and quick-overview user choices;
- Brief objective/focus/depth routing that requires complete fine/replication evidence for detailed or replication-oriented work;
- compact preparation limited to explicit overview mechanism extraction; result comparison stays on `compare-result`;
- explicit `MOTION_REPLICATION`, `NARRATIVE_REPLICATION`, and `HYBRID_REPLICATION` profiles derived from the Brief;
- publication blocked until every exact keyframe has a completed Agent image-understanding receipt with concrete categorized visual facts;
- rejection of boolean-only, `UNAVAILABLE`, `DRAFT:`, and generic viewed/inspected visual attestations;
- publication-time re-decoding of every keyframe from the SHA-verified selected source video in every local publication path;
- rejection of every remaining `DRAFT:` placeholder, including `DRAFT: UNAVAILABLE` and embedded markers;
- content-driven fine segments carrying exact shot/scene ownership and real source-video frames;
- bounded review-frame density inside long semantic segments without inventing duration-based semantic cuts or Beats;
- profile-specific semantic keyframes deduplicated by `(segment_id, timestamp_ms)` with independent action and narrative roles;
- evidenced motion state chains, contact states, adjacent motion transitions, and one bounded Motion Coverage supplementation pass;
- verified facts, grouped events, causal edges, global story roles, repeated product-proof loops, and one bounded Narrative Coverage pass;
- local RGB transition rescans that can recover an unannotated intermediate motion state while keeping unresolved narrative semantics explicit;
- evidence-derived narrative roles with stable role-free supporting frames accepted inside traceable events;
- repeated proof-loop matching across scene, product/style, and added or omitted action-step variations;
- scene/blocking maps plus `MUST_PRESERVE`, `REPLACEABLE`, and `CONDITIONALLY_REPLACEABLE` constraints;
- owner-local `ReferenceBlueprint` with `formal_contract_identity=null` and a shared keyframe timeline;
- publication-time validation of profile/source ownership, semantic roles, transition/event references, coverage additions, and blueprint consistency;
- a finite core-Beat storyboard plus a separate source-frame motion atlas grouped by action;
- atomic publication of all replication JSON, PNG, keyframe, storyboard, and provenance files;
- unchanged production-storyboard and Provider-execution boundaries with zero external counters.

## Fresh verification

| Command | Result |
|---|---|
| `python -m unittest discover -s tests/skills/reference_analysis -t . -p "test_*.py" -v` | PASS - 72 tests, 1 host-capability skip, 0 failures, 552.355s |
| Two-question Analysis Brief interface file | PASS - 11 tests, 0 failures, 115.635s |
| Original combined-choice regression | PASS - 1 test, 0 failures, 0.001s |
| Analysis Brief / image-observation / incomplete-publication regressions | PASS - included in the 72-test owner run |
| Three-profile prepare/finalize flow | PASS - Motion, Narrative, and Hybrid included in the owner run |
| `python -m compileall -q src/ai_video_platform/skills/reference_analysis tests/skills/reference_analysis` | PASS |
| `git diff --check` and owner-scope inspection | PASS |
| Two-axis code review | Standards: 0 hard violations; Spec findings fixed before final owner run |

The owned skip is the existing Windows environment case where symlink creation is unavailable.
No shared implementation changed, so no additional repository-wide suite was required by the
owner-scoped task. The owned skip is the existing Windows environment case where symlink
creation is unavailable.

## Sample status

`run/FT-02-001-reference-analysis-replication-review-03/` predates the new Analysis Brief and
visual-fact gate. It remains historical schema/layout evidence only and is **not** claimed as a
current visually grounded semantic acceptance sample. The synthetic owner fixture uses a test
image-understanding double to verify deterministic schemas, source re-decoding, layouts, and
cross-artifact validation; it is not represented as a truthful garment analysis.

The user's `run/20260729-viral-breakdown` project was intentionally not overwritten or silently
reanalyzed. Under the new contract, a real rerun begins only after the user explicitly supplies
the Analysis Brief, and the execution Agent must then inspect every extracted keyframe. Counters
remain `network_calls=0`, `provider_calls=0`, and `external_upload=false`.

## Scope and blockers

All tracked changes remain limited to `src/ai_video_platform/skills/reference_analysis/**` and
`tests/skills/reference_analysis/**`. No change was made to `storyboard_master_video_planning`,
the root CLI dispatcher, other Skills, shared Contracts, Hermes state, or Provider authorization.

Implementation blocker: none. A new real-video acceptance result awaits the user's explicit
Analysis Brief and an actual all-frame image-understanding pass; this does not block the code.
