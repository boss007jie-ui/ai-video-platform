# Reference Analysis

Version: `0.1.0-rc.offline`; schema and algorithm: `1.0.0`.

Reference Analysis deterministically analyzes one explicitly selected, structured reference and compares a produced result with a compatible analysis. It does not discover references, download or read remote media, call a Provider, traverse Research Library, write Product Library, trigger Storyboard/QA, or import Viral Research implementation.

## Public commands

- `analyze-reference --input request.json --workspace <task-workspace> --output <relative-json>`
- `compare-result --input request.json --workspace <task-workspace> --output <relative-json>`

Both print one machine-readable JSON result and return `0` on success or `2` for a stable redacted error. Hermes calls these commands explicitly and must supply the selected-reference structure; missing input never triggers discovery.

Hermes example: `python -m ai_video_platform.skills.reference_analysis analyze-reference --input selected.json --workspace task-123 --output reference/analysis.json`. The request has exactly `analysis_version` and `selected_reference`; the latter has exactly `reference_id`, `source_uri`, `sha256`, `usage`, `provenance`, and structured `segments`. Compare requests have exactly `analysis_version`, the unchanged analysis artifact, and a `produced_result` with the same selected-reference shape.

## Invariants and outputs

Inputs pin version `1.0.0`, identify the selected reference, carry source digest/provenance, and provide ordered structured segments. Analysis output derives IDs and digests from canonical JSON, never clock/random state. Metrics cover duration, pacing, shot/emotion distributions, visual motifs, hook and CTA positions. Comparison output includes scalar deltas, missing motifs, distribution gaps, and deterministically ordered severity.

The only side effect is one canonical JSON artifact below an existing task workspace. Absolute paths, traversal, link/reparse-point paths, and conflicting output are rejected. Writes use same-directory temporary files, fsync, atomic replacement, cleanup, idempotent replay, and cancellation immediately before replacement.

Read scope is limited to the JSON request supplied by the caller; `source_uri` is provenance only and is never opened. Synthetic fixtures use `task://selected/<id>` URIs and local structured segments. Unsupported/missing versions, malformed/tampered analysis, source identity or digest mismatch, forbidden nested discovery/Provider/download/Library directives, bad segments, unsafe output paths, cancellation, and output collision are blockers.

## Errors, retries, and operation

Stable errors cover validation, forbidden discovery/Provider/download/Library scope, unsupported version, reference mismatch, forbidden path, output conflict, cancellation, and atomic-write failure. Errors recursively redact bearer and secret-like strings. There is no external retryable operation; callers may replay the same deterministic request/output idempotently.

Run the two owned task-card unittest modules, then `python tools\run_offline_tests.py`. Rollback is the owning branch commit revert. Provenance is `CLEAN_ROOM_ONLY`; Provider smoke is not applicable; maintainer `codex-02`; authorization `FTG-0-20260720-001`.

Cancellation is checked before segment analysis and again immediately before publication. One Windows-only symlink regression may skip where the OS denies test symlink creation; code inspection still covers symlink, junction, ancestor, target, and last-moment path changes. Status is an offline release candidate only after the shared placeholder-transition test is updated by its owner.
