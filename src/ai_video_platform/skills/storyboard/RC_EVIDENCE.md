# FT-03-001 Storyboard RC Evidence

## Scope and status

Authorization `FTG-0-20260720-001`; work item `FT-03-001`; owner `codex-03`; branch `ft/codex-03-storyboard`. Implementation is clean-room and offline. No Legacy file was read because no field-complete Codex-03 DV case manifest was found. No adoption proposal or Adoption Manifest change exists.

Current candidate state: `REVIEW`, not `PRODUCTION_READY`. Independent owner tests are implemented; cross-Skill publication, shared Architecture guard activation, DV evidence, Codex-06 acceptance, repository license/SBOM, and merge/release decisions remain external Gates.

## Interface and behavior evidence

- Public module: `StoryboardService`, immutable request/result/artifact types, stable `StoryboardError`.
- CLI: create/revise/validate-continuity commands with machine-readable JSON and stable exit code `2` on rejection.
- Domain: Story/Scene/Beat/Shot/Panel completeness, unique IDs, product identity, configured `required_color`/`logo_visibility` constraints, monotonic emotional progression, and audited continuity transitions.
- State: versioned revisions, validated cross-process exact replay and stale compare-and-set through a working-directory-bound Task Workspace state file, request content hash, changed-digest conflict, terminal cancellation, and an 8 MiB fail-before-write budget.
- Outputs: local Storyboard artifact plus validated Foundation `AssetManifest`, `FeedbackEvent`, and `SkillExecutionEvent`.
- Safety: no Provider/network/private Planning imports; generation/submission-shaped capabilities reject before artifact emission.

## Test evidence

- Owned Interface/Continuity/Failure suites: `36 tests, OK` using deterministic synthetic fixtures only.
- Python stdlib trace line evidence: CLI `87.5%`, Domain `84.0%`, Interface `88.5%`, State `76.1%`; owner runtime weighted line coverage is approximately `85.0%`.
- Branch coverage: not available because no branch-coverage tool is present and this workline cannot add dependencies; Codex-00 release tooling or an FTG-3 waiver is still required.
- Three-Panel local benchmark, 200 fresh-service executions: p50 `1.238 ms`, p95 `1.548 ms`, max `4.439 ms` against a `100 ms` p95 budget.
- Full offline discovery after implementation: `94 tests`, `93 passed`, `1 failed`; the sole failure is the Codex-00-owned baseline assertion that every business namespace must remain a placeholder. `CR-FT-03-001-001` requests its authorized activation update.

## Dependency and Gate ledger

- `CR-FT-03-001-001`: register a Storyboard business artifact identity outside Foundation 1+11 and activate the shared Architecture guard for authorized business Skill contents.
- DV V-01/V-02/V-05: blocked until Hermes provides a field-complete narrow-path manifest; runtime remains clean-room only.
- Codex-06 independent Integration/Golden acceptance: not owned and not run here.
- Codex-00 repository license/SBOM/release manifest: not owned and not present at baseline.
- Provider smoke: `NOT_REQUIRED`; no Provider path exists.

## Known limitations

The Storyboard artifact kind remains owner-local until Codex-00 completes its registry request. Cross-process replay is scoped to callers that explicitly share one Task Workspace state file; no platform-wide state registry was invented. These limitations prevent Production Ready and Released claims.
