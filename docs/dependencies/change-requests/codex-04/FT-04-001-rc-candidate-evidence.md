# FT-04-001 RC Candidate Evidence

Authorization: `FTG-0-20260720-001`
Work item: `FT-04-001`
Workline: `codex-04`
Branch: `ft/codex-04-image-panel`
Baseline: `3bf2c567aebda769ccac22b51b4339541eddb609`
Status: `REVIEW`
Provider smoke: `NOT_AUTHORIZED`
Production Ready claim: `NONE`

## Implemented owner-scoped capability

- independent `generate-product-image`, `generate-panel`, and `inspect-generation-request` API/CLI paths;
- Foundation-bound preflight for TaskSpec, TaskContext, ProductContextBundle, ApprovalRecord, input AssetManifest, and optional ReferenceManifest;
- canonical request hash plus complete model-profile digest binding;
- deterministic product/SKU/asset-bound prompt compilation;
- rejecting and deterministic fake Adapters only, with public direct-call rejection;
- retry, real default backoff, monotonic watchdog timeout, cancellation, partial failure, cost and concurrency limits;
- in-process service idempotency plus atomic, locked, task-workspace CLI replay ledger;
- sanitized generation record, task-owned AssetManifest, FeedbackEvent, and SkillExecutionEvent outputs;
- no Foundation Registry identity addition, no Provider SDK, no network/media operation, and no Legacy mutation.

## Fresh offline verification

| Command | Result |
|---|---|
| `py -3.14 tools\\run_offline_tests.py` | PASS — 120 tests |
| `python -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_interface` | PASS — 21 tests |
| `python -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_adapters` | PASS — 11 tests |
| `python -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_safety` | PASS — 18 tests |
| `python tools\\run_offline_tests.py` | PASS — 120 tests |

These results were captured after merging `ft/codex-00-integration`. The shared architecture guard now recognizes authorized FT-1 Skill packages; the earlier placeholder-only failure is resolved without a Codex-04-owned shared-file edit.

Both full-suite runs separately passed `contracts.test_registry.FoundationRegistryTests.test_registry_is_exactly_one_envelope_and_eleven_payloads`, the repository secret scan, no-provider-SDK/Legacy checks, offline network/subprocess guards, release bundle controls, and reproducible offline wheel build. Fresh raw logs are stored under `logs/hermes-acceptance-20260721/`.

## Review and negative-path closure

Two independent read-only reviews were performed against the task card and implementation. Their substantive findings were closed with tests for:

- mutation of model profile fields after approval;
- zero/negative model cost, dimension multiple, and concurrency ceilings;
- caller-mintable Adapter authorization bypass;
- blocking Adapter work exceeding its timeout;
- Provider-controlled error-message disclosure;
- unrelated contract correlation and invalid asset ownership;
- process-restart CLI replay and same-key/different-hash conflict.

No finding changed Shared Contracts, Core, Main, release, integration-control, or another workline's owner directory.

## Dependency and release blockers

1. Codex-00 must accept or reject the Business Artifact Registry request for the Skill-local generation request and record identities.
2. The synchronized dependency lock still contains no coverage tool. Codex-00 must provide approved offline coverage tooling or an FTG-3 waiver; no dependency installation was attempted.
3. Codex-06 independent acceptance fixtures/results are not yet available on this branch.
4. No production Adapter, credential path, Provider dependency, FTG-P authorization, or real Provider smoke exists. A production orchestration ledger/store is also outside this owner boundary.

Accordingly this evidence is an owner-scoped RC candidate packet only. It does not assert `RC_PROVIDER_PENDING`, `Production Ready`, Provider approval, integration acceptance, or release approval.

## DV and provenance disposition

`DV-codex-04-panel-generation-001` ended `INSUFFICIENT_EVIDENCE` with `CLEAN_ROOM_ONLY` and no adoption proposal. Historical sources were statically inspected only under the six-file allowlist; historical Provider code and tests were not executed. No Adoption Manifest or Legacy source was changed.

## Dependency inventory

Runtime additions: none. The implementation uses Python standard library plus approved in-repository Foundation Contract/Core interfaces. No third-party or Provider package was added, so the workline introduces no new SBOM or license entry; final shared SBOM/license generation remains Codex-00-owned.
