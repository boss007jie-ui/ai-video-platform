# Product Image / Panel Generation Skill

Version: `0.1.0`
Workline: `codex-04`
Provider status: `NOT_AUTHORIZED`
Current release status: `REVIEW`
Target ceiling after gates: `RC_PROVIDER_PENDING` (not yet achieved)

## Responsibility

This Skill validates, compiles, executes, and records independently requested product-image and panel generations. It owns task-local generation requests, generation records, generated task assets, and the corresponding Foundation `AssetManifest`, `FeedbackEvent`, and `SkillExecutionEvent` outputs.

It does not identify products, write Product Library knowledge, publish `ProductContextBundle`, plan video, submit video, make QA decisions, sign `ApprovalRecord`, discover references, or invoke another Skill's private implementation.

## Public commands

The Skill-local CLI is invoked as:

```powershell
python -m ai_video_platform.skills.product_image_panel_generation.cli inspect-generation-request --input <request.json>
python -m ai_video_platform.skills.product_image_panel_generation.cli generate-product-image --input <request.json> --adapter fake
python -m ai_video_platform.skills.product_image_panel_generation.cli generate-panel --input <request.json> --adapter fake
```

`--adapter` accepts only `rejecting` or `fake`. It defaults to `rejecting`. No real Provider adapter or Provider SDK is included. The explicit fake mode is deterministic and offline.

Exit codes are stable:

| Code | Meaning |
|---:|---|
| `0` | inspection approved or all requested items completed |
| `2` | input, contract, authorization, budget, identity, stale-input, or configuration rejection |
| `3` | generation reached the Adapter seam and ended failed, cancelled, or partial |

Every CLI response is one UTF-8 JSON object. Public errors contain `code`, `category`, `retryable`, `message`, `field_paths`, and redacted `details`. They never contain a traceback, secret value, credential, authorization header, or raw Provider payload.

## Input document

The top-level JSON object contains:

- `request`: the Skill-local Image/Panel Generation Request projection;
- `model_profile`: one approved local model profile.

The request binds:

- command, `request_id`, `idempotency_key`, and canonical `request_hash`;
- Foundation `TaskSpec`, `TaskContext`, `ProductContextBundle`, and `ApprovalRecord` envelopes;
- zero or more Foundation input `AssetManifest` envelopes;
- an optional Foundation `ReferenceManifest` envelope;
- exact product/SKU identity and expected TaskContext revision;
- one or more generation items with prompt, role, dimensions, and approved input asset IDs;
- model profile ID, the SHA-256 digest of every model-profile execution field, and explicit cost/attempt/timeout/concurrency budget.

`request_hash` covers every execution-affecting value and Foundation input reference except the approval itself. `ApprovalRecord.subject_ref` must bind both `request_id` and the exact request digest.

## Preflight and invariants

Preflight completes before the service can invoke the private Adapter execution seam. It fails closed unless all of the following are true:

- TaskSpec and TaskContext are valid Foundation contracts for `product-image-panel-generation` and share the same task identity;
- TaskContext revision equals `expected_context_revision`;
- ProductContextBundle is valid, published by Product Knowledge, and matches product/SKU identity;
- every required source asset appears in both the ProductContextBundle approved list and an input AssetManifest with `approval_ref`;
- any non-empty ReferenceManifest has an explicit rights assertion;
- model profile exists, its complete digest matches the approved request binding, Adapter ID matches it, and each dimension is in range and aligned to a positive multiple;
- currency, maximum cost, attempts, timeout, and concurrency are explicit and positive;
- worst-case item × attempt × profile cost does not exceed the approved budget;
- requested concurrency does not exceed either the approved model profile or the local service limit;
- every Foundation input is task-related through the shared task ID, the request correlation ID, or an explicit relationship extension, and input assets are owned by the task or product;
- ApprovalRecord is approved, unexpired, authority-valid under Foundation validation, and bound to the request hash;
- the supplied request hash equals the canonical clean-room compilation.

Prompts are compiled deterministically with product identity, optional SKU, role, dimensions, sorted approved asset IDs, and whitespace-normalized instruction text. Approval internals and credential material are never compiled into the prompt.

## Provider seam and side effects

The public Adapter method always rejects with `IMAGE_PANEL_PROVIDER_BYPASS_FORBIDDEN`. The service reaches only the private execution seam after preflight; no permit issuer or caller-mintable bypass token exists.

- `FakeImageProviderAdapter` produces deterministic in-memory bytes and can script success, retryable failure, non-retryable failure, timeout, cancellation, and partial outcomes.
- `RejectingImageProviderAdapter` always returns `IMAGE_PANEL_PROVIDER_NOT_AUTHORIZED` after validated orchestration reaches the seam.
- no production Adapter, SDK, endpoint, credential lookup, upload, download, subprocess, or socket path exists in this release candidate.

The fake Adapter emits `memory://offline/...` task-asset URIs only. It does not write Product Library, Research Library, Legacy sources, another Skill, or a real task asset directory.

## Idempotency, retry, timeout, cancellation, and concurrency

- Exact `(idempotency_key, request_hash)` replay returns the recorded immutable outcome and does not repeat Adapter work.
- CLI executions persist that replay record in an atomic, locked JSON ledger beside the task input; it is rejected in Product Library, Research Library, or Legacy paths. The direct Python service keeps an in-process ledger only.
- Reusing a key with a different hash fails with `IMAGE_PANEL_IDEMPOTENCY_CONFLICT`.
- A concurrent exact replay fails retryably with `IMAGE_PANEL_IDEMPOTENCY_IN_PROGRESS`.
- Global service concurrency and request concurrency budget are independently enforced.
- Retry occurs only for a sanitized error marked retryable, never beyond `max_attempts`.
- Backoff is deterministic: `0.05 * 2^(attempt-1)` seconds capped at one second, using real sleep by default and an injectable sleeper for tests.
- A daemon watchdog enforces the per-attempt monotonic deadline. Timeout is terminal and recorded as `IMAGE_PANEL_PROVIDER_TIMEOUT`; a late worker result is discarded.
- Cancellation is cooperative before and after the Adapter seam and produces a cancelled execution event.
- Successful and failed items coexist as `partial_failure`; successful assets remain in the task-owned AssetManifest.

## Stable errors

Public codes use the `IMAGE_PANEL_*` namespace:

```text
IMAGE_PANEL_CONTRACT_INVALID
IMAGE_PANEL_REQUEST_HASH_MISMATCH
IMAGE_PANEL_PRODUCT_CONTEXT_REQUIRED
IMAGE_PANEL_PRODUCT_IDENTITY_MISMATCH
IMAGE_PANEL_ASSET_NOT_APPROVED
IMAGE_PANEL_REFERENCE_RIGHTS_UNCONFIRMED
IMAGE_PANEL_BUDGET_REQUIRED
IMAGE_PANEL_BUDGET_EXCEEDED
IMAGE_PANEL_DIMENSIONS_INVALID
IMAGE_PANEL_MODEL_PROFILE_INVALID
IMAGE_PANEL_APPROVAL_REQUIRED
IMAGE_PANEL_APPROVAL_NOT_EFFECTIVE
IMAGE_PANEL_APPROVAL_SUBJECT_MISMATCH
IMAGE_PANEL_STALE_INPUT
IMAGE_PANEL_SKILL_BINDING_INVALID
IMAGE_PANEL_IDEMPOTENCY_CONFLICT
IMAGE_PANEL_IDEMPOTENCY_IN_PROGRESS
IMAGE_PANEL_CONCURRENCY_LIMIT_EXCEEDED
IMAGE_PANEL_PROVIDER_BYPASS_FORBIDDEN
IMAGE_PANEL_PROVIDER_NOT_AUTHORIZED
IMAGE_PANEL_PROVIDER_FAILED
IMAGE_PANEL_PROVIDER_TIMEOUT
IMAGE_PANEL_CANCELLED
```

## Output artifacts

Each terminal generation produces:

1. a Skill-local immutable generation record containing request hash, profile binding, sanitized item outcomes, attempts, cost, and timestamps;
2. a task-owned Foundation `AssetManifest` containing successful assets only;
3. a Foundation `FeedbackEvent` proposing no direct knowledge mutation;
4. a Foundation `SkillExecutionEvent` with terminal status and bounded metrics.

Foundation Registry identity remains exactly one Envelope schema plus eleven payload IDs. The Skill-local request and generation-record identities are pending Codex-00 Business Artifact Registry review under the work-item change request; this branch does not add Foundation IDs.

## Read/write boundary

Read: explicit Foundation contract inputs, approved in-memory source-asset metadata, and the specified local CLI input file.
Write: JSON to stdout, task-local immutable result objects, and the atomic CLI replay ledger beside the explicit task input.
Forbidden: Product/Research Library writes, Legacy access, credential files, shared Contract/Core/schema edits, other Skill implementation imports, real Provider/network/media operations, and Adoption Manifest changes.

## Tests

```powershell
python -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_interface
python -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_adapters
python -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_safety
python tools\run_offline_tests.py
```

The owned suite uses synthetic contracts and in-memory content only. Full-suite promotion remains gated on Codex-00 accepting the architecture-guard change request that retires the launch-baseline placeholder-only assertion for authorized owner directories.

## Operations and rollback

- Normal offline release mode is `rejecting`; enable `fake` only for deterministic tests or demonstrations.
- Kill switch: replace any configured Adapter with `RejectingImageProviderAdapter`.
- Rollback: revert the single Codex-04 work-item commit or omit it from the Codex-00 merge queue; no migration, persistent store, or external side effect needs reversal.
- Direct service replays are process-local in `0.1.0`; CLI replays survive process restart in the task-workspace ledger. A production orchestration store remains a Codex-00 integration prerequisite before Production Ready.
- Real image paths remain `RC_PROVIDER_PENDING` until each Provider has a separate FTG-P, dependency approval, bounded smoke, and redacted evidence.

## Packaging and license

Runtime dependency inventory: Python standard library plus the platform's approved Foundation Contracts and Core guard modules. No third-party package or Provider SDK was added. License/SBOM generation is owned by Codex-00 release tooling; the Codex-04 dependency request records that no runtime dependency change is requested.
