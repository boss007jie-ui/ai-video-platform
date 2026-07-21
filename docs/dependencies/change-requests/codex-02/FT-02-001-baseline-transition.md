# FT-02-001 Implemented-Skill Baseline Transition Request

- Requester: `codex-02`
- Authorization: `FTG-0-20260720-001`
- Work item: `FT-02-001`
- Owner requested: `codex-00`
- Status: `BLOCKING_SHARED_TEST_UPDATE_REQUESTED`

## Problem

The shared architecture test `tests.architecture.test_clean_room_boundaries.CleanRoomBoundaryTests.test_business_namespaces_are_placeholders_only` still requires every business Skill namespace to contain only `__init__.py` and forbids `SKILL.md`. That baseline invariant conflicts with the task-card-authorized implementation of the two Codex-02 owned Skills.

Codex-02 must not modify shared architecture tests. The focused owned suites pass, while the complete offline suite fails only on this stale placeholder assertion.

## Decision requested

Codex-00 should replace the placeholder-only invariant with an authorization-aware boundary check for implemented owner directories. The replacement should continue to fail closed for unassigned namespaces and should enforce allowed ownership paths, no forbidden shared imports, no Legacy runtime dependency, no Product Library writes and no uncontrolled Provider/network access.

## Acceptance

- Both authorized Codex-02 Skill directories and their `SKILL.md` files are permitted.
- Unassigned business namespaces remain placeholders.
- Foundation Registry remains exactly one Envelope plus eleven payload IDs.
- `python tools\run_offline_tests.py` is green after integration without weakening network, secret, path or ownership guards.

## Rollback

If this branch is not integrated, retain the current placeholder test unchanged. No shared file is changed by this request.
