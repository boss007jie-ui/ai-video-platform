# Product Knowledge Skill

Version: `1.0.0`
Owner: `codex-01` / `product-knowledge`

## Responsibility

Product Knowledge is the sole controlled business writer for Product Library and the sole publisher of `ProductContextBundle`, `ProductReviewContext`, and product-knowledge `RuleRef` artifacts. It identifies and matches products/SKUs, records versioned facts and assets with provenance, isolates ambiguity and conflicts, consumes immutable `FeedbackEvent` inputs, verifies review/approval authority, and consolidates confirmed learning.

It does not generate storyboards or media, call Providers, search Legacy roots, decide QA outcomes, sign `ApprovalRecord`, or re-emit `FeedbackEvent`.

## Public commands

`identify-product`, `match-product`, `create-product`, `create-sku`, `ingest-product`, `organize-assets`, `resolve-conflict`, `build-product-context`, `build-product-review-context`, `record-feedback`, `confirm-feedback`, and `consolidate-learning`.

Run the owned CLI without the shared root CLI:

```powershell
python -m ai_video_platform.skills.product_knowledge.cli identify-product --library C:\approved\product-library --input request.json
```

Input is one bounded UTF-8 JSON object. Output is one JSON object with `ok`, `skill_id`, `skill_version`, a `result` or stable `error`, and a validated `SkillExecutionEvent`.

## Contracts and invariants

- Foundation Registry remains one Envelope plus eleven payload identities.
- Inputs may include `AssetManifest`, `FeedbackEvent`, `ReviewDecision`, and `ApprovalRecord`.
- Published outputs use registered `ProductContextBundle`, `ProductReviewContext`, and `RuleRef` identities.
- `ProductContextBundle` contains only active, confirmed, non-inferred, effective facts; approved assets; and approved/effective rules with provenance.
- Pending, inferred, ambiguous, conflicting, and unapproved knowledge is isolated in review state.
- Rule scope is exactly `product`, `sku`, `category`, `skill`, `provider`, or `global`; provider/model/version are bindings, never a new scope.
- `ReviewDecision` cannot replace `ApprovalRecord`; both must bind the current immutable subject digest.
- Every write requires Product Knowledge writer identity, actor, reason, idempotency key, input digest, and expected revision.

## Storage seams

- `InMemoryProductLibrary`: deterministic test/fake adapter.
- `FilesystemProductLibrary`: local production adapter using exclusive writer lock, optimistic concurrency, atomic metadata replacement, append-only audit in the authoritative state, best-effort audit mirrors, verified snapshots, and isolated restore.

The filesystem adapter is offline and has no Provider or network seam. Constructing it initializes only the explicitly supplied root. This release does not initialize the external production Product Library automatically.

## Side effects and blocking

Writes change only the configured Product Library root. Validation happens before commit. Writes fail closed for non-owner identity, stale revision, reused idempotency key with different input, unknown aggregate, missing provenance, invalid scope/binding, subject mismatch, insufficient approval, lock timeout, snapshot tamper, or restore path escape.

Exit codes: `0` success, `2` validation/contract, `3` conflict/stale/idempotency, `4` authorization, `5` missing/invalid state, `70` sanitized internal failure.

Budgets: CLI input is at most 1 MiB; local metadata snapshots are at most 32 MiB per read; lock wait defaults to 5 seconds; the synthetic RC budget is 500 in-memory matches across 100 products in under 2 seconds. Budget excess fails closed or fails acceptance rather than silently truncating data.

## Idempotency, retry, rollback

Exact command replay returns the original result without a new revision or audit entry. Version and lock conflicts are retryable after rereading state. Writes are never auto-retried. Roll back by restoring a verified snapshot; restore creates a new monotonic revision and audit entry while preserving current audit/idempotency history.

## Offline tests

```powershell
python -m unittest -v tests.skills.product_knowledge.test_product_knowledge_interface
python -m unittest -v tests.skills.product_knowledge.test_product_library_adapters
python -m unittest -v tests.skills.product_knowledge.test_product_knowledge_failures
python tools\run_offline_tests.py
```

All fixtures are synthetic. Tests perform no network, Provider, Legacy, credential, or real media access.

## Hermes example

Hermes writes an approved JSON request file, invokes one explicit command, reads the machine result, and records the returned `SkillExecutionEvent`. Hermes never edits Product Library files and cannot gain writer authority through orchestration.

## Codex maintenance

Implementation is owned under this directory. Shared Contract or dependency changes must be requested under `docs/contracts/change-requests/codex-01` or `docs/dependencies/change-requests/codex-01`; only Codex-00 may implement them.
