# Reference Analysis - Offline RC Evidence

## Identity and status

- Authorization: `FTG-0-20260720-001`
- Work item: `FT-02-001`
- Branch: `ft/codex-02-research-reference`
- Implementation evidence head: `e6b7375`
- Schema/algorithm version: `1.0.0`
- Status: `RC_OFFLINE`
- Production Ready: **not claimed**
- Provenance: `CLEAN_ROOM_ONLY`; no Legacy source was read, copied, tested or adopted

The public interfaces are `analyze_reference` and `compare_result`. They accept an already selected structured reference or a synthetic Foundation `ReferenceManifest`-shaped fixture. They do not discover, search, download, call Providers, access Libraries, or write Product Library.

## Implemented offline behavior

- deterministic versioned analysis and comparison artifacts with canonical digests;
- immutable source ID/SHA/provenance linkage and strict input/artifact schemas;
- duration, pacing, shot, emotion, motif, hook and CTA metrics;
- ordered scalar, shot and emotion comparison gaps;
- cancellation before analysis, stable errors and recursive redaction;
- atomic no-clobber output, collision handling and temporary-file cleanup;
- traversal, absolute path and symlink output rejection where the host supports link creation;
- recursive selected-reference-only enforcement for Provider/discovery/download/Library/Legacy directives and location-like values without blocking benign provenance prose;
- independent CLI and `SKILL.md`, with no private import from Viral Research.

## Fresh verification at implementation evidence head

| Command | Result |
|---|---|
| `python -m unittest -v tests.skills.reference_analysis.test_reference_analysis_interface` | PASS - 6/6, 0.083s |
| `python -m unittest -v tests.skills.reference_analysis.test_reference_analysis_failures` | PASS - 5 passed, 1 host-capability skip, 0.058s |
| `python tools\run_offline_tests.py` | BLOCKED SHARED BASELINE - 88 passed, 3 host-capability skips, 1 stale placeholder-only assertion; 92 total, 0.819s |

The Reference skip is a Windows environment where symlink creation is unavailable; the test fails closed when link creation is supported. No line-coverage tool or new dependency was introduced, so a coverage percentage is not claimed. The focused Reference acceptance surface contains 12 tests.

## Security, dependency and operations evidence

- Real Provider, network, media and download smoke: outside this Skill and `NOT_AUTHORIZED`.
- Credential values: not read, displayed, copied or tested.
- Runtime dependencies in this Skill: Python standard library and local Skill modules only; no package/lock change.
- Repository secret scan, Legacy-root guard and network/subprocess guards pass in the complete suite.
- Performance evidence is bounded offline unit execution only; no production throughput/SLA claim.
- Independent review after the final scope-validation fix found no Critical, Important or Minor issue.
- Rollback: Codex-00 can omit or revert commits `cfee0e1`, `75d3952`, `ae0d5e5`, `75d5f3a`, and `c6505f8`; no production artifact migration exists.

## Open gates

1. Codex-00 update of the shared placeholder-only architecture test.
2. Shared contract decision for the Reference Collection Manifest handoff; synthetic fixtures keep this RC independent meanwhile.
3. Windows/link-capable CI execution of the skipped symlink case.
4. Integration/Golden testing by the authorized integration owner.

Next gate requested: `FTG-2` for shared handoff and integration-boundary review.
