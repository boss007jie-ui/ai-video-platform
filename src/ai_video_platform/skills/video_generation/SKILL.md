# Video Generation

Status: `RC_PROVIDER_PENDING`; local interface version `0.1.0`; DV status
`CLEAN_ROOM_ONLY`. Real Provider smoke is `NOT_AUTHORIZED` without FTG-P.

The public `inspect_video_request` / `inspect-video-request` surface validates an
unregistered draft VideoExecutionPackage, effective ApprovalRecord, budget limits,
opaque Provider binding reference, deterministic request hash, and idempotency key.
It returns a safe provider summary without a credential reference and records
`provider_execution_performed: false`.

Preflight order is fixed and fail-closed: validate the execution package and its
nested master first, then ApprovalRecord, budget, Provider binding plus opaque
credential reference, output controls, and idempotency key; only then derive the
request hash. Every validation completes before an adapter, ledger, filesystem, or
other side-effect seam may be invoked.

Video Generation does not rewrite storyboards, import Planning implementation,
write Product Library, read Legacy, inspect credential values, access a network,
download media, or create a formal business identity. Draft business artifacts
remain `DRAFT_UNREGISTERED` pending the Codex-00 Business Artifact Registry gate.

## Public command and side effects

```text
python -m ai_video_platform.skills.video_generation.cli inspect-video-request <file|->
```

The CLI reads exactly the named local JSON file or stdin and writes one JSON result
to stdout. Exit `0` is ready; exit `2` is a fail-closed rejection. Preflight has no
Provider or filesystem write side effect. Submit/poll/cancel/download are added only
behind fake/rejecting/network-blocked adapters in the next offline task.

Stable errors cover package identity/version/digest, ApprovalRecord effectiveness
and subject binding, budgets, Provider binding, opaque credential reference, and
idempotency input. Errors recursively redact credential/token-like fields and values.
Corrected inputs may be retried; deterministic request hashing supplies the basis
for exact replay and mismatch handling in the execution ledger.

Hermes example: call `inspect-video-request` with package, approval, budget,
provider-binding reference, output controls, and idempotency key. Route `ready` to
the separately authorized execution command only when that adapter/gate exists;
otherwise keep the task blocked. Hermes never resolves the credential reference.

## Tests and rollback

```text
python -m unittest -v tests.skills.video_generation.test_video_generation_interface
python -m unittest -v tests.skills.video_generation.test_video_generation_safety
```

Rollback by reverting the owning commits. Preflight creates no Provider job, remote
asset, credential, Library write, or formal Contract registration to undo.
