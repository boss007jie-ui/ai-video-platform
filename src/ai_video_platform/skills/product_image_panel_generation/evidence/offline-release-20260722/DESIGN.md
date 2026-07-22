# Product Image / Panel Offline Release Closeout Design

Authorization: `FTG-0-20260720-001`
Workline: `codex-04`
Scope: offline release closeout plus Provider-neutral FTG-P preparation
Provider execution: `NOT_AUTHORIZED`

## Goal and non-goals

This change makes the existing offline Image/Panel capability independently demonstrable and prevents an incomplete future real Provider Adapter from being silently instantiated or passed into orchestration.

It does not select a Provider, define a real endpoint, request or read credentials, download media, make a network call, run a real image generation, or claim Production Ready.

## Provider-neutral Adapter contract

Add an `ImageProviderAdapter` abstract base class in `adapters.py`:

- an abstract `provider_id` property is required;
- an abstract private `_generate(invocation, cancellation=...)` method is required;
- the concrete public `generate(...)` method is shared by every Adapter and always raises `IMAGE_PANEL_PROVIDER_BYPASS_FORBIDDEN`;
- `FakeImageProviderAdapter` and `RejectingImageProviderAdapter` inherit the ABC and implement both abstract members;
- `ImagePanelService` requires an `ImageProviderAdapter` instance and rejects duck-typed objects before preflight or execution;
- no real Adapter class is added.

This gives two fail-closed layers: an incomplete subclass cannot be instantiated, and a non-ABC object cannot enter the service.

## CLI behavior and evidence flow

The CLI keeps its explicit `--adapter {rejecting,fake}` allowlist and default `rejecting`; no dynamic Provider selection, import path, plugin name, environment switch, or fallback is added.

One sanitized sample uses two deterministic input documents:

1. a Fake profile/request for inspection, generation, and exact replay;
2. a Rejecting profile/request with a distinct request ID and idempotency key.

Actual Python 3.14 module CLI processes produce:

1. `inspect` output proving approved preflight and the bound request digest;
2. Fake generation output proving prompt compilation reached the Adapter seam, generated only `memory://offline/...` metadata, and emitted the generation record plus Foundation result envelopes;
3. exact replay output proving the result-management ledger prevents repeated Adapter work;
4. Rejecting output proving default-deny Provider behavior and `provider_smoke=NOT_AUTHORIZED`;
5. a sanitized copy of the task-workspace ledger as the receipt of immutable request-hash/outcome binding.

The evidence bundle contains JSON and Markdown only. It contains no image bytes, encoded binary, secret, credential, real URL, real Provider identifier, or real product/customer data.

## Evidence artifact set

The directory containing this design will contain:

- `sanitized-fake-request.json`
- `sanitized-rejecting-request.json`
- `01-inspect.stdout.json`
- `02-fake.stdout.json`
- `03-replay.stdout.json`
- `04-rejecting.stdout.json`
- `ledger-receipt.json`
- `OFFLINE_RELEASE_RECORD.md`
- `FTG-P-003-PROVIDER-AUTHORIZATION-SKELETON.md`

The FTG-P card intentionally leaves Provider selection, endpoint, pricing, quota, input constraints, and credential reference type as explicit `TBD_BY_HERMES_AFTER_USER_DECISION` fields. Credential values are never fields in the card.

## Tests

TDD adds Adapter contract tests before implementation:

- an incomplete `ImageProviderAdapter` subclass cannot instantiate;
- a duck-typed object is rejected by `ImagePanelService`;
- Fake and Rejecting are concrete ABC implementations;
- the inherited public direct-call surface remains fail-closed;
- the existing scripted Fake and default Rejecting behavior remains unchanged;
- CLI adapter selection stays an explicit two-value allowlist.

Final verification clears `PYTHONPATH` and uses `py -3.14` for all owned test modules and the full offline suite. Static scans confirm no Provider SDK, network endpoint, credential material, real media, or non-owner path change.

## Commit and rollback design

Use small commits:

1. this approved design;
2. Adapter ABC plus tests;
3. sanitized CLI inputs/outputs, ledger receipt, and FTG-P skeleton;
4. release record referencing the exact capability and evidence commits.

Rollback is additive and Git-native: revert the release-record commit, evidence commit, Adapter commit, and design commit in reverse order. Offline CLI ledger artifacts are task-local JSON; the committed evidence bundle has no external side effect.
