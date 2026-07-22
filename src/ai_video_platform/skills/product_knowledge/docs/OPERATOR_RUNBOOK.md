# Product Knowledge Operator Runbook

## Preconditions

Use Python 3.12+ in the offline platform environment. Confirm the configured Library root is explicit, writable, not a Legacy root, and contains no credential material. Do not point tests at the external production Library.

## Health checks

Run the three owned suites and the full offline runner listed in `SKILL.md`. A healthy filesystem library has valid `metadata/library.json`, no lingering `metadata/*.tmp`, a monotonic `revision`, and an audit chain where each `before_revision` equals the prior `after_revision`.

## Backup

Call `ProductKnowledgeService.backup_library({"actor": ..., "reason": ...})`. Preserve both `library.json` and `manifest.json` in the returned `snapshots/<snapshot-id>` directory. The manifest carries the source revision and canonical state digest.

## Restore drill

1. Stop Product Knowledge writers.
2. Record the current revision and select a snapshot inside this Library's `snapshots` root.
3. Call `ProductKnowledgeService.restore_library` with the snapshot path, exact current expected revision, actor, and reason. The service supplies the private Product Knowledge writer capability; direct adapter calls cannot claim writer authority.
4. Verify the returned new revision is current+1, run integrity checks and owned tests, then resume writers.

Restore rejects path escape, digest mismatch, stale expected revision, and non-owner identity. It restores business state but preserves current append-only audit and idempotency history.

Commands committed after the selected snapshot are marked `restored_out`; replaying their old idempotency keys is rejected so an operator cannot receive a stale success for state that was rolled back. Reread current state and submit an explicitly reviewed new command/key if the change should be applied again.

## Lock recovery

A lock timeout is retryable, but the operator must first establish that no writer process is active. This release deliberately does not auto-delete a lock because doing so could permit concurrent writers. Manual stale-lock removal requires an external operational approval and is not automated by this Skill.

## Rollback

Code rollback is a normal Git revert performed by the integration owner. Data rollback is snapshot restore to a new revision; never replace metadata manually or delete audit/events. The rejecting/offline posture is intrinsic: this Skill has no Provider adapter.

## Incident stops

Stop writes and escalate on secret findings, unexpected network attempts, Legacy paths, non-Product-Knowledge writer identities, audit discontinuity, snapshot digest mismatch, repeated lock timeout, or Foundation Registry drift.
