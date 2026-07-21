# Fast Track Business Artifact Registry V1

Authorization: `FTG-0-20260720-001`  
Registry version: `1.0.0`

This registry is separate from the immutable Foundation Registry. The
Foundation Registry remains one Envelope schema identity and eleven payload
Contract IDs. Registration here does not make a business artifact a valid
`ContractEnvelope.contract_type`; that requires its published schema and
validator at the applicable contract gate.

| Artifact | Identity | Owner | Version |
|---|---|---|---|
| ViralResearchRequest | `avp.contract.viral-research-request` | Viral Research & Asset Collection | `1.0.0` |
| ViralResearchPack | `avp.contract.viral-research-pack` | Viral Research & Asset Collection | `1.0.0` |
| ReferenceCollectionManifest | `avp.contract.reference-collection-manifest` | Viral Research & Asset Collection | `1.0.0` |

Compatibility follows the Shared Contracts reader/writer SemVer matrix:
same-major readers accept writer versions up to their supported minor;
newer-writer minor versions return `reader_too_old`; different majors return
`major_mismatch`.

Consumer migration note: consumers may use the registry metadata for
capability negotiation, but must continue using synthetic branch-local
fixtures until the corresponding versioned schema, validator, and permission
fixtures are published. No legacy artifact is adopted or migrated by this
registration.
