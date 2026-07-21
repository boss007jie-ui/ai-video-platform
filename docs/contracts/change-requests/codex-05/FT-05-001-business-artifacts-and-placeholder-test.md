# FT-05-001 Codex-00 shared-contract change request

- authorization_id: `FTG-0-20260720-001`
- work_item_id: `FT-05-001`
- requester: `codex-05`
- owner_requested: `codex-00`
- status: `REQUESTED_NOT_APPLIED`

## Request

1. Update the Codex-00-owned clean-room architecture assertion
   `test_business_namespaces_are_placeholders_only`. An authorized Production Fast
   Track owner now supplies `SKILL.md` and implementation files in the Planning and
   Video Generation namespaces, so “placeholder only” is no longer a valid invariant
   for those two owner directories. Preserve the Legacy, network, credential,
   Product Library, Provider SDK, and ownership guards.
2. Review the local `DRAFT_UNREGISTERED` shapes `StoryboardMaster`,
   `VideoExecutionPackage`, and `AssetManifestRequest` at the next business-artifact
   contract gate. Codex-05 does not request or perform automatic registration.

## Non-negotiable registry constraint

The Foundation Registry must remain exactly 1 Envelope + 11 payload IDs. This
request does not authorize adding, renaming, or removing any Foundation identity.
If business-artifact registration is approved later, Codex-00 must choose a path
that preserves that invariant and issue the separate authorization/gate evidence.

## Evidence

- Codex-05 exact Skill tests pass offline.
- `python tools\run_offline_tests.py` has one deterministic failure at the obsolete
  placeholder-only assertion; the other architecture/security/contract tests pass,
  including exact Foundation Registry identity.
- The draft artifacts carry `schema_version: 0.1.0` and
  `contract_status: DRAFT_UNREGISTERED` and are not emitted as formal Contracts.

## Requested disposition

Codex-00 should either accept and implement the narrow shared-test update, or return
a replacement invariant/change request. Until then Codex-05 reports the broad suite
as one known shared-owner failure and does not modify the test itself.
