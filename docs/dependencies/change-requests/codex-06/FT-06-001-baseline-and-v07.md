# Dependency Change Request: Fast Track Guard and V-07 Inputs

Request ID: `DR-FT-06-001-A`
Owners requested: `codex-00`, Hermes/CatPaw evidence route
Requester: `codex-06`
Status: `PARTIALLY_RESOLVED`

## Dependency 1: phase-aware architecture guard

Resolution: `RESOLVED` by Codex-00 commit `79354a0`. After merging
`ft/codex-00-integration`, the complete offline suite runs 87 tests with result `OK` while
the ownership, security, Foundation, Provider, network, and Legacy guards remain enabled.

At launch baseline, `test_business_namespaces_are_placeholders_only` asserted every Skill
directory contained only `__init__.py`, so an authorized Production Fast Track implementation
made the full offline suite red.

Completed Codex-00 action:

- replace the placeholder-only assertion with a phase-aware ownership/import guard;
- allow `src/ai_video_platform/skills/qa_review/**` on the Codex-06 merge candidate;
- continue rejecting implementation in non-owner Skill paths;
- continue rejecting cross-Skill private imports, Provider SDK imports, Legacy runtime paths,
  secrets, Product/Research Library writes, and Foundation identity drift;
- retain a test that non-authorized Skill namespaces remain placeholders until their owner
  commits are merged.

Original evidence: the pre-sync full offline suite ran 74 tests and only the shared baseline
guard failed. Codex-06 did not edit, skip, or weaken the Codex-00-owned test.

## Dependency 2: V-07 allowlist and CatPaw evidence

Resolution: `OPEN`.

T0-T3 Direct Verification requires a registered case manifest and a narrow relative-path
allowlist generated from targeted read-only evidence. Neither is present in the Codex-06
worktree. Reading Legacy roots without them would violate the authorized process.

Requested Hermes/CatPaw action:

- register one V-07 case limited to visual review, panel QA, board drift, QC, storyboard QA,
  or auto-review evidence;
- provide per-file or narrow-directory relative paths under only LSL-01 through LSL-06;
- include source commit/dirty state, hashes, dependencies, test candidates, and side effects;
- exclude credentials, environment files, Provider execution, downloads, and unrelated
  generation/research behavior;
- route the evidence without canonical/adopt/migrate execution decisions.

Until that input exists, Codex-06 remains `CLEAN_ROOM_ONLY` and makes no adoption proposal.

## Acceptance

Dependency 1 is resolved. Dependency 2 will be resolved when a complete, unexpired DV case
manifest and relative allowlist exist; only then may Codex-06 run T0-T3 in isolated staging.

Neither dependency authorizes FTG-P, a real Provider smoke, network access, Legacy writes, an
Adoption Manifest update, or any Library mutation.
