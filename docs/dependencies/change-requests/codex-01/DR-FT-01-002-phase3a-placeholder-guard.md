# Shared Test Change Request: Authorized Skill Implementation Guard

- authorization_id: `FTG-0-20260720-001`
- work_item_id: `FT-01-001`
- requester: `codex-01`
- owner/implementer: `codex-00`
- status: `BLOCKING_FULL_SUITE`

## Reproduction

```powershell
python tools\run_offline_tests.py
```

Fresh result on the Codex-01 worktree: `Ran 76 tests`; 75 passed and only `architecture.test_clean_room_boundaries.CleanRoomBoundaryTests.test_business_namespaces_are_placeholders_only` failed because it asserts `(skill_dir / "SKILL.md").exists()` is false.

## Conflict

The assertion represents the pre-Fast-Track Phase 3A baseline. FTG-0 and `CODEX_01_TASK_CARD.md` explicitly require Codex-01 to create `src/ai_video_platform/skills/product_knowledge/SKILL.md` and owned implementation. Codex-01 cannot modify `tests/architecture/**`.

## Requested change

Update the shared architecture guard so authorized implemented worklines may contain their owned `SKILL.md` and implementation while unauthorized/unmerged business namespaces remain placeholder-only. Preserve checks for ownership, cross-Skill private imports, Legacy runtime paths, Provider/network dependencies, Foundation 1+11 identity, and external Product Library non-creation.

## Acceptance

- The Codex-01 owned implementation is permitted only after its authorized branch is merged.
- Other worklines remain constrained by their own authorization/merge state.
- A non-owner implementation path still fails.
- Full offline suite returns zero failures after the integration owner implements the guard update.
