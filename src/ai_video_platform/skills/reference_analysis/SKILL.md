# Reference Analysis

Version: `0.1.0-rc.offline`; schema and algorithm: `1.0.0`.

Reference Analysis deterministically analyzes one explicitly selected reference, can publish an evidence-bound reference storyboard analysis, and compares a produced result with a compatible analysis. It does not discover references, download remote media, call a Provider, traverse Research Library, write Product Library, trigger Storyboard/QA, or import Viral Research implementation.

## Public commands

- `analyze-reference --input request.json --workspace <task-workspace> --output <relative-json>`
- `analyze-storyboard --input request.json --workspace <task-workspace>`
- `compare-result --input request.json --workspace <task-workspace> --output <relative-json>`

All commands print one machine-readable JSON result and return `0` on success or `2` for a stable redacted error. Hermes calls these commands explicitly and must supply the selected-reference structure; missing input never triggers discovery.

Hermes examples: `python -m ai_video_platform.skills.reference_analysis analyze-reference --input selected.json --workspace task-123 --output reference/analysis.json` and `python -m ai_video_platform.skills.reference_analysis analyze-storyboard --input storyboard-request.json --workspace task-123`. The direct analysis request has exactly `analysis_version` and `selected_reference`; the latter has exactly `reference_id`, `source_uri`, `sha256`, `usage`, `provenance`, and structured `segments`. A synthetic Foundation-shaped mode instead supplies exactly `analysis_version`, `reference_manifest`, and `selected_reference_id`; the manifest must have the registered `ReferenceManifest` required fields and exactly one selected entry with synthetic segments. This mode does not publish or claim a new Contract. Compare requests have exactly `analysis_version`, the unchanged analysis artifact, and a `produced_result` with the direct selected-reference shape.

`analyze-storyboard` accepts the selected local reference video, video metadata, optional `ViralResearchPack`, optional popular comments, and an evidence-bound analysis configuration. It always publishes beneath `reference_analysis/`: the canonical JSON and Markdown, analysis/evidence/replication PNG boards, copied real keyframes, and `analysis_provenance.json`. Its JSON references `ReferenceStoryboardAnalysis`, `ReferenceBeat`, `ReferenceShotEvidence`, `ReplicationPattern`, and `ReferenceAnalysisBoardManifest` at `1.0.0`. Every board and keyframe is non-executable, ineligible as a first frame, and ineligible as a product panel.

## Invariants and outputs

Inputs pin version `1.0.0`, identify the selected reference, carry source digest/provenance, and provide ordered structured segments. Analysis output derives IDs and digests from canonical JSON, never clock/random state. Metrics cover duration, pacing, shot/emotion distributions, visual motifs, hook and CTA positions. Comparison output includes scalar deltas, missing motifs, distribution gaps, and deterministically ordered severity.

The legacy analyze/compare modes write one canonical JSON artifact below an existing task workspace. Storyboard analysis atomically publishes its fixed output directory only after all media, timeline, identity, evidence, and role checks pass. Absolute paths, traversal, link/reparse-point paths, and conflicting output are rejected; identical output replays idempotently.

Legacy analyze/compare read scope is limited to the JSON request supplied by the caller; `source_uri` is provenance only and is never opened. Storyboard analysis reads only the explicitly named workspace-relative selected video and keyframe PNGs, verifies every supplied hash, and never dereferences the source URL. Absolute paths, link paths, and traversal are rejected. Unsupported/missing versions, malformed/tampered analysis, source identity or digest mismatch, missing evidence, forbidden nested discovery/Provider/download/Library directives, bad timelines, unsafe paths, and output collision are blockers.

## Errors, retries, and operation

Stable errors cover validation, missing evidence, invalid media, forbidden artifact roles, forbidden discovery/Provider/download/Library scope, unsupported version, reference mismatch, forbidden path, output conflict, cancellation, and atomic-write failure. Errors recursively redact bearer and secret-like strings. There is no external retryable operation; callers may replay the same deterministic request/output idempotently.

Run `python -m unittest discover -s tests/skills/reference_analysis -p "test_*.py"`, then `python tools\run_offline_tests.py`. Rollback is the owning branch commit revert. Provenance is `CLEAN_ROOM_ONLY`; Provider smoke is not applicable; maintainer `codex-02`; authorization `FTG-0-20260720-001`.

Cancellation is checked before segment analysis and again immediately before publication. One Windows-only symlink regression may skip where the OS denies test symlink creation; code inspection still covers symlink, junction, ancestor, target, and last-moment path changes. Status is an offline release candidate only after the shared placeholder-transition test is updated by its owner.
