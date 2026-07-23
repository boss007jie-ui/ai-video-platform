# Storyboard Operator, Release, and Rollback Runbook

## Release identity

- Interface SemVer: `1.1.0`
- Python compatibility target: `>=3.12`
- Foundation Contracts consumed/emitted: `1.0.0`
- Provider smoke: `NOT_REQUIRED` (Storyboard owns no Provider path)
- Adoption mode: `CLEAN_ROOM_ONLY`

## Preflight

Confirm branch/worktree, clean input Contracts, active Skill `storyboard`, one confirmed product/SKU, required `ReferenceManifest`, `expected_version`, a caller-owned idempotency key, and explicit `task_workspace` plus `state_file` paths. Supply either the existing structured plan or a non-empty `raw_script`; raw-script planning options must request 6-12 Panels. Configure `AVP_TASK_WORKSPACE_ROOT` at launch (or launch from the trusted Task Workspace); `task_workspace` must equal that trusted root and the resolved state file must remain inside it. Never supply `ProductReviewContext`, pending facts, credentials, media payloads, Provider settings, or a Legacy path.

Run the three owned suites, then the full offline runner. A release packet is not mergeable while any ownership, secret/network/legacy scan, shared change request, DV, or Codex-06 acceptance item is unresolved.

## Operational budgets

- Canonical plan input: maximum `1,048,576` UTF-8 bytes.
- Storyboard size: maximum `500` Panels for structured compatibility input; automatic raw-script planning is restricted to `6-12` Panels.
- Owner-local replay/version state: maximum `8 MiB`, rejected before replacing a valid state file.
- Provider/network calls: exactly `0`.
- Target local latency: p95 below `100 ms` for the synthetic three-Panel fixture; max-Panel stress evidence is recorded in `RC_EVIDENCE.md` when run.
- Cost budget: `0` external calls and `0` Provider cost.

Budget excess fails with `STORYBOARD_BUDGET_EXCEEDED` before artifact emission.

## Failure handling

- Validation/compatibility/conflict/authorization/state failures: correct input or version; do not retry with changed input under the same key.
- Exact replay: reuse the same key and exact request; result is marked `replayed`.
- Stale revision: fetch the immutable current artifact and intentionally rebuild the revision request.
- Cancellation: terminal `SkillExecutionEvent` with no Storyboard artifact or AssetManifest.
- Continuity conflict: declare exact `from`, `to`, and non-empty reason at the changing Panel, or preserve prior state.

## Release and rollback

The owner branch commit is the rollback unit. Codex-00 merges only after shared requests and acceptance evidence are resolved. To roll back an already merged change, the merge owner creates a normal `git revert` of the Storyboard commit/merge commit and reruns affected owned, Contracts, Architecture, Security, and full offline suites. Do not use `reset --hard` or delete task artifacts.

Existing versioned Storyboard artifacts remain immutable after rollback. The capability rejecting guard remains fail-closed, so rollback cannot enable Provider calls.

## SBOM and license inventory

Runtime imports use only Python standard library, the repository's `ai_video_platform.contracts` package, and Foundation `core.guards` for path enforcement. No third-party dependency or Provider SDK is added. Repository-level license metadata and release SBOM generation are Codex-00-owned and currently requested as release evidence; absence blocks a Production Ready claim but does not change the offline test result.
