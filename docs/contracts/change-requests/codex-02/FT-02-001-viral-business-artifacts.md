# FT-02-001 Business Artifact Registry Change Request

- Requester: `codex-02`
- Authorization: `FTG-0-20260720-001`
- Work item: `FT-02-001`
- Owner requested: `codex-00`
- Status: `REQUESTED_NOT_APPLIED`

## Decision requested

Register the following identities in the separate Business Artifact Registry, without changing the Foundation Registry envelope or its eleven payload IDs:

1. `avp.contract.viral-research-request`
2. `avp.contract.viral-research-pack`
3. `avp.contract.reference-collection-manifest`

Codex-02 has not added these identities to Contracts, schemas, or either registry. The current clean-room implementation uses local immutable models until Codex-00 approves the identities and publishes the shared contracts.

## Requested contract work

For each identity, Codex-00 should freeze a SemVer `1.0.0` schema, positive and negative fixtures, producer/consumer permissions, compatibility rules, and envelope mapping. Proposed ownership is:

| Identity | Producer | Consumers | Purpose |
|---|---|---|---|
| `avp.contract.viral-research-request` | Viral Research caller | Viral Research | Inspection/research/collection intent, limits, time window and policy inputs |
| `avp.contract.viral-research-pack` | Viral Research | Orchestrator and explicitly authorized downstream Skills | Ranked metadata, provenance, rights/safety/retention decisions and explanations |
| `avp.contract.reference-collection-manifest` | Viral Research or user selection flow | Reference Analysis | Selected reference IDs and immutable source metadata; no discovery authority |

The contracts must not grant Product Library writes, Provider calls, downloads, credential access, or Legacy runtime access. Reference Analysis must accept only an already selected item and must remain independently testable with synthetic fixtures.

## Acceptance conditions

- Foundation Registry remains exactly one Envelope plus eleven payload IDs.
- New identities exist only in the approved Business Artifact Registry.
- Fixtures cover metadata-only, quarantine, expiry, selected-reference-only and stable-error cases.
- Producer/consumer permissions and migration/rollback notes are explicit.
- Codex-02 receives the approved shared contract references before replacing local models.

## Rollback

Do not integrate the identities into this branch. If the request is rejected or revised, retain the local `1.0.0` models and rejecting seams; no runtime or stored data migration is required.
