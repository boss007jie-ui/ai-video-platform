# Reference Analysis

Version: `0.4.2-rc.offline`; schema and algorithm: `1.0.0`.

Reference Analysis deterministically analyzes one explicitly selected reference, publishes source-bound observations and reusable reference mechanisms, and compares a produced result with a compatible analysis. It does not discover references, download remote media, call a Provider, traverse Research Library, write Product Library, adapt mechanisms to a current product, create production Storyboards, trigger QA, or import another Skill's implementation. Product transfer belongs to Storyboard and product facts belong to Product Knowledge.

## Public commands

- `analyze-reference --input request.json --workspace <task-workspace> --output <relative-json>`
- `prepare-reference-breakdown --input request.json --workspace <task-workspace>`
- `finalize-reference-analysis --input request.json --workspace <task-workspace>`
- `analyze-storyboard --input request.json --workspace <task-workspace>` (compatibility alias)
- `compare-result --input request.json --workspace <task-workspace> --output <relative-json>`

All commands print one machine-readable JSON result and return `0` on success or `2` for a stable redacted error. Hermes calls these commands explicitly and must supply the selected-reference structure; missing input never triggers discovery.

Hermes examples: `python -m ai_video_platform.skills.reference_analysis analyze-reference --input selected.json --workspace task-123 --output reference/analysis.json` and `python -m ai_video_platform.skills.reference_analysis finalize-reference-analysis --input reference-analysis-request.json --workspace task-123`. The legacy direct analysis request has exactly `analysis_version` and `selected_reference`; the latter has exactly `reference_id`, `source_uri`, `sha256`, `usage`, `provenance`, and caller-supplied structured `segments`. This legacy path summarizes supplied structure and does not satisfy the local visual-observation workflow or authorize new semantic claims. A synthetic Foundation-shaped mode instead supplies exactly `analysis_version`, `reference_manifest`, and `selected_reference_id`; the manifest must have the registered `ReferenceManifest` required fields and exactly one selected entry with synthetic segments. This mode does not publish or claim a new Contract. Compare requests have exactly `analysis_version`, the unchanged analysis artifact, and a `produced_result` with the direct selected-reference shape.

`finalize-reference-analysis` accepts the selected local reference video, video metadata, optional `ViralResearchPack`, optional popular comments, an explicit `analysis_brief`, and an evidence-bound analysis configuration. It always publishes beneath `reference_analysis/`: the canonical JSON and Markdown, analysis/evidence/replication PNG boards, copied real keyframes, and `analysis_provenance.json`. Its JSON references `ReferenceStoryboardAnalysis`, `ReferenceBeat`, `ReferenceShotEvidence`, `ReplicationPattern`, and `ReferenceAnalysisBoardManifest` at `1.0.0`. Every board and keyframe is non-executable, ineligible as a first frame, and ineligible as a product panel.

### Mandatory analysis brief and visual observation gate

Before either local preparation mode, the execution Agent must obtain an explicit `analysis_brief` with exactly `objective`, non-empty `focus`, `depth`, and `hypothesis_policy`. The user does not need to understand those internal fields. If intent is not already explicit, the Agent must use the following two questions in order and map the answers deterministically with `build_analysis_brief_from_choices`; it may not select a target on the user's behalf.

#### Required two-question interaction

**Question 1 - replication target**

Present these as separate, intuitive choices:

1. `MOTION_1_TO_1` — **1:1 动作复刻** / 1:1 motion replication: inspect body/hand movement, contact state, object trajectory, timing, camera position, and scene blocking.
2. `NARRATIVE_1_TO_1` — **故事剧情复刻** / story/narrative replication: inspect facts, events, causal continuity, turns, reveals, product-proof story function, pacing, subtitles, and audiovisual structure.
3. `HYBRID_1_TO_1` — **动作 + 剧情完整复刻** / motion + story replication: perform both detailed analyses with a shared source timeline.
4. `QUICK_OVERVIEW` — **快速了解视频结构** / quick structural overview: inspect only the main stages, editing rhythm, and audiovisual structure; do not claim 1:1 replication.

**Question 2 - inference policy**

Ask this only after the replication target is known:

1. `FACTS_ONLY` — **只写画面可确认的事实** / observed facts only: inference fields remain `UNAVAILABLE`.
2. `LABELED_HYPOTHESES` — **允许补充为什么有效，但标记为待验证假设** / labeled hypotheses allowed: every inference uses the `HYPOTHESIS:` prefix and remains separate from observed facts.

**Never combine the two questions into precomposed bundles.** In particular, do not offer choices such as “detailed + facts only” or “overview + hypotheses” before the user has selected motion, narrative, hybrid, or overview. Every mode still requires real-frame viewing; image grounding is not an inference-policy option.

The mapping is fixed: Motion → `REPLICATION_REFERENCE` + `MOTION,SCENE_BLOCKING` + `DETAILED`; Narrative → `REPLICATION_REFERENCE` + `NARRATIVE,EDITING_RHYTHM,AUDIO_VISUAL` + `DETAILED`; Hybrid → all replication focuses + `DETAILED`; Overview → `MECHANISM_EXTRACTION` + `EDITING_RHYTHM,AUDIO_VISUAL` + `OVERVIEW`. Question 2 maps only to `OBSERVED_ONLY` or `LABEL_UNVERIFIED`. Supported focus values remain `EDITING_RHYTHM`, `MOTION`, `NARRATIVE`, `PRODUCT_PROOF`, `SCENE_BLOCKING`, and `AUDIO_VISUAL`. Reference Analysis derives the technical replication profile from this brief; there is no silent Hybrid default, and a caller-supplied conflicting profile is rejected. Detailed or replication-oriented work requires the complete fine-segment and replication package. Compact preparation accepts only the explicit quick overview. `RESULT_COMPARISON` is rejected by preparation/finalization and must use `compare-result`.

The execution Agent **must look at every extracted keyframe with image-understanding before publication**. Preparation writes `analysis_configuration.visual_observation` as a `REQUIRED` checklist bound to the selected media SHA-256 and every keyframe ID/SHA-256. After actually opening and inspecting each image, the Agent must record one or more concrete `visual_facts` for that exact frame. Each fact has `category` (`SCENE`, `SUBJECT`, `ACTION`, `OBJECT_STATE`, `VISIBLE_TEXT`, `CAMERA`, or `FRAME_QUALITY`) and a concrete `description`; `UNAVAILABLE`, `DRAFT:`, and generic “viewed/inspected” attestations are rejected. Only then may the Agent set the checklist to `COMPLETED`, identify itself, set `method=agent_image_understanding`, and mark the frame observed. The Agent must never auto-complete this receipt with a script or test helper. Copying the checklist without viewing the images, or inferring content from filenames, scripts, metadata, prior reports, subtitles alone, or other text is forbidden. If image understanding is unavailable, any image cannot be opened, or any digest/observation/fact is missing, the Agent must stop and report `REFERENCE_ANALYSIS_VISUAL_OBSERVATION_REQUIRED`; it must not invent an analysis.

An all-frame receipt is necessary but not sufficient. Every supplied keyframe is re-decoded from the SHA-verified selected source video at publication time. Any `DRAFT:` placeholder produced during extraction, including `DRAFT: UNAVAILABLE`, is rejected even after the checklist is marked complete. The Agent must replace it with image-grounded observations or exact `UNAVAILABLE`. Audience psychology, conversion function, and viral mechanism are inference fields: `OBSERVED_ONLY` makes them unavailable, while `LABEL_UNVERIFIED` requires the `HYPOTHESIS:` prefix. Target-product transfer suggestions must remain `UNAVAILABLE` because Storyboard owns that work.

### Local draft preparation

`prepare-reference-breakdown` is the first stage of the local-video workflow. Its request has
`analysis_version=1.0.0`, `mode=local_draft_v1`, an explicit `analysis_brief`, and the same complete
`selected_reference_video` object consumed by `analyze-storyboard`. The media path and every
generated asset path are workspace-relative and link/traversal paths fail closed. The selected
video SHA-256 must match before metadata probing or extraction.

`video_metadata` is optional. When supplied, all six strict fields (`duration_ms`, `width`,
`height`, `aspect_ratio`, `media_type`, and `codec`) are preserved and provenance records
`caller_supplied`; otherwise the local `ffprobe` executable detects them and provenance records
`local_ffprobe`. Keyframes are always decoded locally by `ffmpeg`; missing/rejected local tools
are blockers, with no cloud or Provider fallback.

The optional policy defaults to `interval_ms=2000` and `max_keyframes=12`. Sampling always
includes 0 ms and a decodable near-end point (`duration_ms-100`); a requested maximum above 12 or a computed sample count above
the requested maximum is rejected rather than truncated. Current-product context is not required or used; compatibility input is validated but published as `UNAVAILABLE` so adaptation stays in Storyboard.

The fixed `reference_breakdown_draft/` output contains `draft_manifest.json`,
`keyframes/*.png` plus `keyframes/index.json`, `draft_timeline.json`,
`draft_bottom_line_formula.json`, and `analyze_storyboard_request.json`. Every timeline
observation starts with `DRAFT:` and states that visual interpretation is unconfirmed. The
package is non-executable, never a first frame or production storyboard, records
`provider_calls=0` and `external_upload=false`, and its request is an observation template, not a publishable analysis. The Agent must view the extracted images, complete the visual receipt, and replace draft placeholders before calling `finalize-reference-analysis`. Cloud video LLM, Provider, upload, and any mode other than
an explicitly supported local mode are rejected.

### Fine-segment storyboard preparation

`prepare-reference-breakdown` also accepts `mode=local_fine_segments_v1` through the same
public command. It first creates content-driven candidate boundaries from local RGB frame
differences and optional local audio boundaries. The default `max_review_interval_ms=8000` guard adds source-video `review` keyframes inside a long semantic segment so the execution Agent cannot skip a long visual interval. It does not create a semantic cut, Beat, or fixed segment count; segmentation remains evidence-driven. An optional owner-local offline analyzer may
add evidence-bound semantic boundary signals and exact segment annotations. If the policy or
offline analyzer is absent, conservative local defaults and explicit `UNAVAILABLE` observations
are used; no network or Provider fallback exists.

Fine segments are ordered, contiguous half-open source intervals with exact previous/next links
and evidence-bearing segmentation reasons. Every segment receives real `start`,
`representative`, and `end` PNG frames decoded from the selected source video. Every frame
records its source video, segment, timestamp, role, workspace-relative asset path, and SHA-256.
Supplied offline observations cover scene, shot/camera position, camera and subject motion,
primary action, product state, props, visible text, audio function, emotion, attention,
audience psychology, narrative function, viral mechanism, and conversion function. Every
non-`UNAVAILABLE` observation cites an in-segment real frame.

Only adjacent fine segments with the same available narrative, psychology, mechanism, action,
and product-state purpose are merged. Each core beat preserves `source_segment_ids`,
`source_frame_ids`, exact interval, `representative_frame_id`, and `merge_reason`. The bottom
formula is derived from the ordered confirmed core-beat titles and evidence; it is not an
independent free-form claim.

The draft additionally publishes `fine_segments.json`, `keyframes/index.json`,
`segment_analysis.json`, `draft_core_beats.json`, and an `analyze_storyboard_request.json`
directly consumable by the publication seam.

### Replication profiles and blueprint

`local_fine_segments_v1` uses three technical `analysis_profile` values:
`MOTION_REPLICATION`, `NARRATIVE_REPLICATION`, and `HYBRID_REPLICATION`. The value is derived
from `analysis_brief.focus`; callers may repeat it only when it matches the derivation. The same
value is propagated into the publication request and every replication artifact. Motion and
narrative profiles use different semantic keyframe criteria. A physical source frame is stored
once per `(segment_id, timestamp_ms)` even when it carries both action and narrative roles.

The offline analyzer may supply exact `segment_contexts`, evidenced `motion_actions`,
`narrative_facts`, and `scene_annotations`. Fine segmentation and semantic frame counts remain
content-driven: the review fixture's 10 fine segments, 30 base frames, and 5 core beats are an
example, not a fixed ratio or quota. Motion analysis preserves evidenced state chains from
action start through contact, control, apex, release/end, and final hold as applicable. Narrative
analysis proceeds from facts to events, causal edges, global story roles, and repeated product
proof loops. Each coverage mode performs at most one bounded source-evidence supplementation
pass and never invents a missing frame or story event.

For 1:1 motion work, one action chain must describe one observable motion mechanism. Distinct
paths or contact changes such as horizontal stretching, downward pressing, lifting, and release
must be separate chains unless the chain label and every state explicitly describe the compound
sequence. Every state and timestamp must agree with that frame's recorded `ACTION` and
`OBJECT_STATE` visual facts. If an earlier reviewed frame already shows the action or contact
state, the Agent must move the onset to that evidence or split the chain; it may not keep a later
RGB-difference candidate as the semantic onset. A local scan is only a candidate locator, never
proof of what the action is. When no viewed frame supports a state, the Agent must leave the state
unavailable and report incomplete coverage instead of guessing.

The bounded coverage pass reuses the same locally decoded RGB transition scan that informs fine
segmentation. When caller annotations omit an intermediate motion state, a non-zero source-video
change between evidenced endpoints may add one conservative onset, contact, release, apex, or end
state; the state records its local scan method, timestamp, and score. A narrative discontinuity
also triggers an interval rescan, but a visual probe never becomes a fabricated fact: unresolved
semantic continuity remains explicit in `coverage_report.json`.

Global story roles are derived from event text, verified state changes, revelations, and explicit
stage cues rather than event position. Stable supporting fact frames may remain role-free while
retaining event ownership; a role-bearing event needs at least one—not every—source frame carrying
one of its roles. Repeated product-proof detection compares retained ordered action subsequences,
so scene, product/style, and added or omitted action-step variations can share one structure ID.

The publication seam validates profile/source consistency, shot and scene ownership, semantic
roles, duplicate timestamp storage, action-state and transition endpoints, narrative event
evidence, scene blocking references, coverage-added frames, and blueprint component equality.
Every requested capability must be `PASS`; missing motion actions, narrative facts, or scene
blocking is `INCOMPLETE`, never an empty `PASS`, and publication fails with
`REFERENCE_ANALYSIS_INCOMPLETE`.
It then re-decodes every keyframe from the selected SHA-verified local video before atomically
publishing. `ReferenceBlueprint` remains an owner-local payload with
`formal_contract_identity=null`; no formal Contract identity is added.


## Invariants and outputs

Inputs pin version `1.0.0`, identify the selected reference, carry source digest/provenance, and provide ordered structured segments. Analysis output derives IDs and digests from canonical JSON, never clock/random state. Metrics cover duration, pacing, shot/emotion distributions, visual motifs, hook and CTA positions. Comparison output includes scalar deltas, missing motifs, distribution gaps, and deterministically ordered severity.

The legacy analyze/compare modes write one canonical JSON artifact below an existing task workspace. Storyboard analysis atomically publishes its fixed output directory only after all media, timeline, identity, evidence, and role checks pass. Absolute paths, traversal, link/reparse-point paths, and conflicting output are rejected; identical output replays idempotently.

For a fine-segment request, the final `reference_analysis/` output includes
`fine_segments.json`, real `keyframes/`, `segment_analysis.json`,
`reference_storyboard_analysis.json`, `reference_storyboard_analysis.md`,
`reference_storyboard_analysis_board.png`, and `analysis_provenance.json`. Existing shot-evidence
and replication boards remain supporting owner-local analysis assets. The main board uses a
black/orange horizontal core-beat layout headed `分镜故事板 / Storyboard`; each card uses only
its source-video representative frame and concise stage, action, audience, and function copy.
Every source frame is fitted without changing its aspect ratio; portrait frames use neutral
letterboxing instead of horizontal stretching. Board copy preserves Unicode through the native
Windows CJK renderer, wraps by rendered character width, and fails explicitly when a suitable
Unicode font renderer is unavailable rather than substituting question marks.
The first generated board is a review candidate, not a final visual approval.

When a complete replication package is supplied, the same output also includes
`motion_keyframes.json`, `motion_transitions.json`, `motion_keyframe_atlas.png`,
`narrative_event_graph.json`, `scene_blocking_map.json`, `replication_constraints.json`,
`coverage_report.json`, and `reference_blueprint.json`. The motion atlas groups source-video
frames by action in timestamp order and labels action state, timestamp, and direction. Detailed
motion evidence stays in these dedicated artifacts while the human storyboard remains a finite
set of merged core beats.

Fine publication rejects gaps, overlaps, bad adjacency links, cross-segment frames or evidence,
partial analysis packages, non-adjacent or incomplete beat partitions, representative-frame
mismatches, and formulas not derived from the ordered beats. Provenance records
`network_calls=0`, `provider_calls=0`, and `external_upload=false`. Reference blueprints and
boards are analysis evidence only: they are not production storyboard plans, first frames, or
Provider execution inputs.

Legacy analyze/compare read scope is limited to the JSON request supplied by the caller; `source_uri` is provenance only and is never opened. Storyboard analysis reads only the explicitly named workspace-relative selected video and keyframe PNGs, verifies every supplied hash, and never dereferences the source URL. Absolute paths, link paths, and traversal are rejected. Unsupported/missing versions, malformed/tampered analysis, source identity or digest mismatch, missing evidence, forbidden nested discovery/Provider/download/Library directives, bad timelines, unsafe paths, and output collision are blockers.

## Errors, retries, and operation

Stable errors cover validation, missing evidence, required visual observation, incomplete requested analysis, invalid media, forbidden artifact roles, forbidden discovery/Provider/download/Library scope, unsupported version, reference mismatch, forbidden path, output conflict, cancellation, and atomic-write failure. Errors recursively redact bearer and secret-like strings. There is no external retryable operation; callers may replay the same deterministic request/output idempotently.

Run `$env:PYTHONPATH='src'; python -m unittest discover -s tests/skills/reference_analysis -t . -p "test_*.py"`, then `python tools\run_offline_tests.py`. Rollback is the owning branch commit revert. Provenance is `CLEAN_ROOM_ONLY`; Provider smoke is not applicable; maintainer `codex-02`; authorization `FTG-0-20260720-001`.

Cancellation is checked before segment analysis and again immediately before publication. One Windows-only symlink regression may skip where the OS denies test symlink creation; code inspection still covers symlink, junction, ancestor, target, and last-moment path changes. Status is an offline release candidate only after the shared placeholder-transition test is updated by its owner.
