# Product Image / Panel Offline Release Closeout Design

Authorization: `FTG-0-20260720-001`
Workline: `codex-04`
Scope: offline release closeout plus Provider-neutral FTG-P preparation
Provider execution: `NOT_AUTHORIZED`

## Goal and non-goals

This change makes the existing offline Image/Panel capability independently demonstrable and prevents an incomplete future real Provider Adapter from being silently instantiated or passed into orchestration. The completed offline capability may report `INTERNAL_PRODUCTION_READY_OFFLINE`; the real image Provider path remains `RC_PROVIDER_PENDING`.

It does not select a Provider, define a real endpoint, request or read credentials, download media, make a network call, run a real image generation, or claim Production Ready.

## Provider-neutral Adapter contract

Add an `ImageProviderAdapter` abstract base class in `adapters.py`:

- an abstract `provider_id` property is required;
- an abstract internal `_generate(invocation, cancellation=...)` method is required;
- the concrete public `generate(...)` method is shared by every Adapter and always raises `IMAGE_PANEL_PROVIDER_BYPASS_FORBIDDEN`;
- `FakeImageProviderAdapter` and `RejectingImageProviderAdapter` inherit the ABC and implement both abstract members;
- `ImagePanelService` requires an `ImageProviderAdapter` instance and rejects duck-typed objects before preflight or execution;
- no real Adapter class is added.

The leading underscore is a Python naming convention, not a security or authentication boundary. Fail-closed enforcement comes from four independently tested controls: incomplete subclasses cannot instantiate, non-ABC objects cannot enter the service, public `generate()` always rejects, and a production-source AST guard permits `_generate(...)` call sites only in `service.py` and `adapters.py`.

The AST guard scans every Python module under `src/ai_video_platform`. It reports the relative path and line for each disallowed `_generate` call. Its tests exercise both the clean repository and a synthetic forbidden module so a future bypass makes the owned architecture suite fail.

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

The Adapter contract receipt records invocation counts of `1` after the first Fake execution and `1` after exact replay. Tests independently assert the same invariant.

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
- `receipt-manifest.json`
- `python-runtime.txt`
- `static-scan.txt`
- `OFFLINE_RELEASE_RECORD.md`
- `FTG-P-003-PROVIDER-AUTHORIZATION-SKELETON.md`

The FTG-P card intentionally leaves Provider selection, endpoint, pricing, quota, input constraints, and credential reference type as explicit `TBD_BY_HERMES_AFTER_USER_DECISION` fields. Credential values are never fields in the card.

## Tests

TDD adds Adapter contract tests before implementation:

- an incomplete `ImageProviderAdapter` subclass cannot instantiate;
- a duck-typed object is rejected by `ImagePanelService`;
- Fake and Rejecting are concrete ABC implementations;
- the inherited public direct-call surface remains fail-closed;
- a normal service execution calls the internal Adapter implementation once;
- exact replay leaves the internal invocation count at one;
- the AST guard rejects a direct `_generate` call outside `service.py` and `adapters.py`;
- the existing scripted Fake and default Rejecting behavior remains unchanged;
- CLI adapter selection stays an explicit two-value allowlist.

`pyproject.toml` remains authoritative at `requires-python = ">=3.12"`; Codex-04 does not edit that shared file. Final verification clears `PYTHONPATH` and uses Python 3.14 for all owned test modules and the full offline suite. A single minimal Python 3.12 CLI/interface smoke is also required; the full suite is not duplicated on 3.12. The release record names both runtime commands and results. Static scans confirm no Provider SDK, network endpoint, credential material, real media, or non-owner path change.

## Commit and rollback design

Use small commits:

1. this approved design;
2. Adapter ABC plus tests;
3. sanitized CLI inputs/outputs, ledger receipt, and FTG-P skeleton;
4. release record referencing the exact capability and evidence commits.

Rollback is additive and Git-native: revert the release-record commit, evidence commit, Adapter commit, and design commit in reverse order. Offline CLI ledger artifacts are task-local JSON; the committed evidence bundle has no external side effect.
