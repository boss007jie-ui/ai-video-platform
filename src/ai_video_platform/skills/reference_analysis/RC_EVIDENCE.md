# Reference Analysis - Replication Blueprint Offline Evidence

## Identity and status

- Authorization: `FTG-0-20260720-001`
- Work item: `FT-02-001`
- Branch: `ft/codex-00-integration`
- Implementation baseline: `dc6865a`
- Schema/algorithm version: `1.0.0`
- Skill version: `0.4.3-rc.offline`
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
- aspect-ratio-preserving visual inspection atlases with at most 12 labelled frames per batch, while retaining exact per-frame facts and fail-closed individual-frame fallback;
- preparation bindings that invalidate stale publication requests and completed receipts whenever a newer/different fine preparation becomes current;
- rejection of boolean-only, `UNAVAILABLE`, `DRAFT:`, and generic viewed/inspected visual attestations;
- publication-time re-decoding of every keyframe from the SHA-verified selected source video in every local publication path;
- rejection of every remaining `DRAFT:` placeholder, including `DRAFT: UNAVAILABLE` and embedded markers;
- content-driven fine segments carrying exact shot/scene ownership and real source-video frames;
- bounded review-frame density inside long semantic segments without inventing duration-based semantic cuts or Beats;
- profile-specific semantic keyframes deduplicated by `(segment_id, timestamp_ms)` with independent action and narrative roles;
- evidenced motion state chains, contact states, adjacent motion transitions, and one bounded Motion Coverage supplementation pass;
- one-observable-mechanism-per-action-chain guidance that binds state timing to viewed `ACTION`/`OBJECT_STATE` facts rather than raw RGB candidates;
- verified facts, grouped events, explicit adjacent-event transitions, causal edges, global story roles, repeated product-proof loops, and one bounded Narrative Coverage pass;
- source-shot discontinuities represented as non-causal `MONTAGE_CUT` transitions without fabricated bridge facts;
- local RGB transition rescans that can recover an unannotated intermediate motion state while keeping same-shot unresolved narrative semantics explicit;
- evidence-derived narrative roles with stable role-free supporting frames accepted inside traceable events;
- repeated proof-loop matching across scene, product/style, and added or omitted action-step variations;
- scene/blocking maps plus `MUST_PRESERVE`, `REPLACEABLE`, and `CONDITIONALLY_REPLACEABLE` constraints;
- owner-local `ReferenceBlueprint` with `formal_contract_identity=null` and a shared keyframe timeline;
- publication-time validation of profile/source ownership, semantic roles, transition/event references, coverage additions, and blueprint consistency;
- a finite core-Beat storyboard plus a separate source-frame motion atlas grouped by action;
- aspect-ratio-preserving source-frame placement across every board, with neutral letterboxing;
- Unicode CJK board text, rendered-width wrapping, and fail-closed handling when no Unicode renderer is available;
- encoding-safe ASCII JSON emission from the CLI so GBK terminals remain machine-readable;
- atomic publication of all replication JSON, PNG, keyframe, storyboard, and provenance files;
- unchanged production-storyboard and Provider-execution boundaries with zero external counters.

## Fresh verification

| Command | Result |
|---|---|
| `python -m unittest discover -s tests/skills/reference_analysis -t . -p "test_*.py"` | PASS - 77 tests, 1 host-capability skip, 0 failures, 692.712s |
| Two-question Analysis Brief interface file | PASS - 11 tests, 0 failures, 115.635s |
| Original combined-choice regression | PASS - 1 test, 0 failures, 0.001s |
| Board aspect-ratio / CJK rendering plus GBK-safe CLI regressions | PASS - 3 tests, 0 failures, 4.337s |
| Analysis Brief / image-observation / incomplete-publication regressions | PASS - included in the 77-test owner run |
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

The real Hybrid run `run/20260730-raulpi025-viral-ra/output/reference_analysis/` was replayed from
its saved grounded publication request after the board-rendering fix. It completed with a 21/21
Agent visual receipt and 133 concrete frame facts. All four boards were visually inspected: source
frames retain their portrait aspect ratio, Chinese copy is readable, and rendered-width wrapping
stays inside the cards. The pre-fix output remains recoverable at
`run/20260730-raulpi025-viral-ra/output/reference_analysis_before_board_render_fix/`.

The independent real-video preparation at
`run/20260730-童装爆款拆解-ra-fixed-validation/reference_breakdown_draft/` reuses the user's
56.233-second children's-clothing reference and its saved offline annotations without modifying
the original failed run. Motion, Narrative, and overall coverage are `PASS`; the three former
inter-event gaps are now three evidence-bound, non-causal `MONTAGE_CUT` transitions across
`shot-001→002`, `shot-002→003`, and `shot-003→004`. The 71 exact keyframes are covered in order by
6 digest-bound inspection atlases. Atlas 001 was visually inspected at original resolution and
preserves every portrait frame without stretching. This preparation remains `REQUIRED`, not a
claimed all-frame visual final, because no synthetic receipt was used for the real sample.

## Scope and blockers

All tracked changes remain limited to `src/ai_video_platform/skills/reference_analysis/**` and
`tests/skills/reference_analysis/**`. No change was made to `storyboard_master_video_planning`,
the root CLI dispatcher, other Skills, shared Contracts, Hermes state, or Provider authorization.

Implementation blocker: none. A new real-video acceptance result awaits the user's explicit
Analysis Brief and an actual all-frame image-understanding pass; this does not block the code.
