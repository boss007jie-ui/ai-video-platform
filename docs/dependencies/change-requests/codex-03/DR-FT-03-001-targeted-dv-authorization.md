# DR-FT-03-001 — Storyboard targeted DV authorization request

## Routing

- Authorization: `FTG-0-20260720-001`
- Work item: `FT-03-001`
- Requester/workline: `codex-03`
- Owner requested: `Hermes / Codex-00`
- Status: `BLOCKED_AUTHORIZATION`
- Requested capability scope: Storyboard semantics and continuity only under V-01, V-02, and the Storyboard half of V-05.

## Missing prerequisite

No field-complete Codex-03 DV case manifest has been authorized. Accordingly, Codex-03 has not read, copied, diffed, imported, executed, wrapped, refactored, migrated, or modified a Legacy candidate. No `.dv-staging` directory was created and no CatPaw investigation was started.

Hermes may unblock only by issuing one capability-level manifest containing every required field:

- `case_id`, `workline_id`, `owner`, and one narrowly named `capability`;
- permitted `legacy_root_ids` limited to LSL-01/02/03/04/06;
- file-level or narrow-directory `relative_path_allowlist[]`, never a root-only allowlist;
- frozen `source_commit_dirty_state` and per-file `source_sha256[]`;
- explicit `tests_allowed[]` for T0, T1, T2, and T3;
- `side_effect_controls`, `expected_interface_mapping`, `evidence_output`, and `expiry`.

Missing any field must fail closed.

## Requested offline execution boundary

- T0: read-only hashes, imports, entrypoints, schemas, tests, and side-effect inspection.
- T1: approved Foundation Contract parsers plus synthetic Story/Scene/Beat/Shot/Panel fixtures in isolated staging.
- T2: minimal candidate tests with fixed time, seed, and dependencies; stop if dependency closure exceeds the allowlist.
- T3: fake/rejecting adapters, permission/path escape, retry/cancellation, and redaction checks; network remains denied.

The comparison must keep Storyboard semantic ownership separate from Storyboard Master / Video Planning asset-mapping ownership. It may assess public behavior and continuity only; it may not declare a whole-project winner.

## Explicit exclusions

- No credential value, `.env`, token, private user data, or real Provider configuration may be read or displayed.
- No network, media download, Provider smoke, Legacy write/cleanup, or source-state mutation.
- No automatic wrap, adoption, migration, deprecation, or `08_ADOPTION_MANIFEST.json` change.
- CatPaw `canonical`, `adopt`, or `migrate` language is non-executing evidence only.

## Safe state until authorization

Execution strategy remains `CLEAN_ROOM_ONLY`. The deterministic owner implementation, 36 owner tests, and 302-test full offline suite remain the accepted internal path. A future DV verdict is evidence for a separate Adoption Gate and cannot silently replace the clean-room implementation.

## Rollback

This request creates no runtime or Legacy state. Withdraw or close the request document if Hermes declines the case; no code, artifact, or Foundation identity rollback is required.
