# Contract/Core Change Request: Trusted Producer Attestation

- authorization_id: `FTG-0-20260720-001`
- work_item_id: `FT-01-001`
- requester: `codex-01`
- owner/implementer: `codex-00`
- status: `BLOCKING_AUTHORITY_HARDENING`

## Problem

Foundation `ContractEnvelope` validates declared `producer.agent` and `producer.component_id`, but the current baseline has no trusted attestation/signature/verifier interface proving that a serialized CLI caller is the declared producer. Product Knowledge can mechanically reject a QA-produced `ApprovalRecord`, yet an untrusted caller could serialize the authorized component strings.

This matters for `FeedbackEvent`, `ReviewDecision`, and especially `ApprovalRecord` promotion. Codex-01 cannot add shared authentication, modify `ContractEnvelope`, or create a parallel identity scheme.

## Requested decision

Provide a shared trusted-artifact verification seam in Contracts/Core or an authenticated Hermes handoff that returns an already-attested immutable Contract artifact. The seam must:

- bind contract ID, payload digest, producer agent/component/version, and authorization context;
- be injectable with a deterministic fake/rejecting verifier for offline tests;
- fail closed for standalone/raw CLI claims lacking attestation;
- expose no credential value and require no network;
- preserve Foundation Registry at one Envelope plus eleven payload IDs.

## Current behavior

Product Knowledge validates all declared producers through Foundation contract validation and requires ReviewDecision/ApprovalRecord subject digests and decision references to agree. This is mechanical contract authorization, not cryptographic or OS-level producer authentication. Standalone CLI must therefore be treated as an authorized local caller boundary until Codex-00 resolves this request.
