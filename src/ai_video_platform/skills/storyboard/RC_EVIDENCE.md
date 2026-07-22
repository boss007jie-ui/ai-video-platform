# FT-03-001 Storyboard RC Evidence

## Scope and status

Authorization `FTG-0-20260720-001`; work item `FT-03-001`; owner `codex-03`; branch `ft/codex-03-storyboard`. Implementation is clean-room and offline. No Legacy file was read because no field-complete Codex-03 DV case manifest was authorized. No adoption proposal or Adoption Manifest change exists.

Current Skill state: `INTERNAL_PRODUCTION_READY`, per Hermes directive dated 2026-07-22. This is an internal, Provider-free acceptance state; it is not a Released claim and does not authorize cross-Skill publication of the owner-local Storyboard artifact.

## Interface and behavior evidence

- Public module: `StoryboardService`, immutable request/result/artifact types, stable `StoryboardError`.
- CLI: create/revise/validate-continuity commands with machine-readable JSON and stable exit code `2` on rejection.
- Domain: Story/Scene/Beat/Shot/Panel completeness, unique IDs, product identity, configured `required_color`/`logo_visibility` constraints, monotonic emotional progression, and audited continuity transitions.
- State: versioned revisions, validated cross-process exact replay and stale compare-and-set through a working-directory-bound Task Workspace state file, request content hash, changed-digest conflict, terminal cancellation, and an 8 MiB fail-before-write budget.
- Outputs: local Storyboard artifact plus validated Foundation `AssetManifest`, `FeedbackEvent`, and `SkillExecutionEvent`.
- Safety: no Provider/network/private Planning imports; generation/submission-shaped capabilities reject before artifact emission.
- Integration: Codex-00 merged the Storyboard RC through `ac1bad9`; a generic public three-command interface entry is present in `fixtures/integration/skill-rc-candidates-v1.json` from `3c9ae6b`. That fixture does not freeze or publish a Storyboard business artifact identity.

## Fresh verification — 2026-07-22

All commands ran in the current worktree after fast-forward synchronization to Codex-00 integration `047a2c2`, with `PYTHONPATH` absent and Python 3.14:

- `py -3.14 -m unittest -v tests.skills.storyboard.test_storyboard_interface`: `11 tests`, `OK`.
- `py -3.14 -m unittest -v tests.skills.storyboard.test_storyboard_continuity`: `4 tests`, `OK`.
- `py -3.14 -m unittest -v tests.skills.storyboard.test_storyboard_failures`: `21 tests`, `OK`.
- `py -3.14 tools\run_offline_tests.py`: `302 tests`, `OK`, `skipped=3` because symlink creation is unavailable on the host.

Fresh logs:

`C:\Users\boss0\Desktop\05-项目文件夹\AI Video Platform Re-architecture Control\.codex-tmp\codex03\hermes-next-20260722`

`00_preflight.log` records the branch, pre-commit HEAD, dirty owner-document paths, timestamp, and `PYTHONPATH_PRESENT=False`. The four numbered test logs contain the corresponding command outputs; a post-commit status log is recorded alongside them.

The full suite proves the Foundation Registry remains exactly one Envelope plus eleven payload IDs, the separate Business Artifact Registry does not contaminate that invariant, shared ownership/AST guards pass, the Storyboard public interface appears in RC integration fixtures, and offline release/reproducibility tests pass.

Previously measured owner runtime line coverage was approximately `85.4%`; branch coverage was not remeasured because no owner-authorized branch-coverage dependency is present. The three-Panel local benchmark remains p50 `1.351 ms`, p95 `1.660 ms`, max `4.849 ms` against a `100 ms` p95 budget.

## Dependency and Gate ledger

- `CR-FT-03-001-001`: requester-side work is complete. Shared guard activation and Storyboard code integration are resolved; frozen-identity fixture routing and canonical cross-Skill Storyboard artifact identity/mapping/carrier decisions remain with Codex-00.
- `DR-FT-03-001-targeted-dv-authorization`: requests a field-complete, capability-level V-01/V-02/V-05 T0–T3 manifest. Until granted, execution remains `CLEAN_ROOM_ONLY` and no Legacy path may be read.
- Provider smoke: `NOT_AUTHORIZED`; no FTG-P authorization exists and Storyboard owns no Provider path.

## Known limitations and rollback

The Storyboard artifact remains owner-local until Codex-00 completes the shared identity decision. Cross-process replay is scoped to callers that explicitly share one Task Workspace state file; no platform-wide state registry was invented. These limitations do not reverse Hermes' internal acceptance, but they prohibit a Released or cross-Skill publication claim.

Codex-03 rollback is a normal `git revert` of the Codex-03 evidence/code commit, followed by owner, Architecture, Contracts, Integration/Golden, Security, and full offline suites. Any rollback of a shared integration commit is owned and executed only by Codex-00 under the merge runbook. Do not use `reset --hard`, delete versioned Storyboard artifacts, or touch Legacy.
