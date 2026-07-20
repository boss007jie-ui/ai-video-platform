# FT-02-001 Apify Adapter Dependency Request

- Requester: `codex-02`
- Authorization: `FTG-0-20260720-001`
- Work item: `FT-02-001`
- Owner requested: `codex-00`
- Status: `REQUESTED_NOT_APPLIED`
- Provider gate: `FTG-P NOT_AUTHORIZED`

## Decision requested

Decide whether an Apify production adapter and dependency may be introduced behind the Viral Research Provider Seam. Codex-02 added no package, lockfile, credential integration, network call, actor binding, or production adapter.

Before implementation, Codex-00 should approve:

- the exact package and pinned version;
- actor IDs/versions, input and output schemas, supported locales and platform scope;
- request, concurrency, duration and cost budgets;
- credential-reference handling without exposing values;
- retry, timeout, cancellation, kill-switch and rejecting-fallback behavior;
- metadata-only defaults, rights/PII/retention handling and log redaction;
- SBOM/license review and rollback procedure.

## Mandatory runtime gate

Even after a dependency decision, every real Provider smoke or download remains blocked until a separate, bounded `FTG-P` approval records provider/actor, credential reference, budgets, observation window and cleanup. Fake and rejecting adapters remain the only executable adapters on this branch.

## Acceptance and rollback

Acceptance requires offline contract tests, deterministic fake fixtures, fail-closed network guards and no import-time side effects. Rollback removes the separately owned production adapter/dependency while preserving the current rejecting seam; no Codex-02 schema or stored-artifact migration is required.
