# FT-04-001 Image/Panel Contract And Architecture Guard Change Request

Status: `REQUESTED_CODEX_00_REVIEW`
Authorization: `FTG-0-20260720-001`
Work item: `FT-04-001`
Requester: `codex-04`
Owner requested: `codex-00`

## Request A — Business Artifact Registry

Register two business-artifact identities outside the Foundation Registry:

| Proposed stable identity | Purpose | Producer | Consumers |
|---|---|---|---|
| `avp.artifact.image-panel-generation-request` | Immutable request projection binding Foundation inputs, product/SKU, items, request hash, profile, and budget | Authorized direct caller or Hermes | Product Image / Panel Generation Skill |
| `avp.artifact.image-panel-generation-record` | Immutable generation audit record with per-item outcome, attempts, cost, profile binding, and source request hash | Product Image / Panel Generation Skill | Hermes, QA / Review, audit/release tooling |

This request explicitly does not add, rename, or alias any Foundation identity. The Foundation Registry must remain exactly `ContractEnvelope` plus the eleven existing payload IDs.

Requested schema behavior:

- UTF-8 JSON, SemVer `1.0.0`, canonical SHA-256 content digest;
- generation request approval binds `request_id` plus digest;
- generation record is task-owned and append-only;
- no binary, credential, raw Provider payload, or Product Library mutation content;
- unknown additive fields follow Foundation V1 reader/writer compatibility rules;
- stable errors retain the Skill-local `IMAGE_PANEL_*` namespace unless Codex-00 freezes a shared public error registry.

Until accepted, the implementation treats these as Skill-local `0.1.0` projections and does not claim cross-Skill Contract compatibility. Approved outputs remain Foundation `AssetManifest`, `FeedbackEvent`, and `SkillExecutionEvent`.

## Request B — Launch Placeholder Architecture Guard

Update the Codex-00-owned `tests/architecture/test_clean_room_boundaries.py` assertion `test_business_namespaces_are_placeholders_only` for authorized Fast Track implementations.

Current launch-baseline behavior requires every business Skill directory to contain only `__init__.py` and no imports. Any correctly authorized Codex-04 implementation therefore makes the full offline suite red even though all changes remain inside the owner boundary.

Requested replacement behavior:

- keep exact top-level Skill namespace enumeration;
- allow implementation files and `SKILL.md` only for worklines authorized by a recorded FTG-0 work item;
- continue rejecting cross-Skill private imports, Provider SDK imports, Legacy names/paths, unregistered Foundation IDs, and ownership violations;
- preserve placeholder-only assertions for Skill directories that have not entered an authorized implementation work item;
- add a changed-path owner guard instead of inferring authorization from file count.

Codex-04 will not modify the shared architecture test. Until Codex-00 accepts and implements this request, `python tools\run_offline_tests.py` is expected to fail only at the obsolete placeholder assertion after the owned tests pass.

## Acceptance requested

- Codex-00 assigns Contract/Business Artifact decision references;
- Codex-00 implements or rejects the architecture-guard transition with rationale;
- no Foundation Registry identity count or ownership boundary changes;
- Codex-06 receives the frozen public artifact and error semantics for independent acceptance fixtures.
