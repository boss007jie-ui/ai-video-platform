# FT-03-002R Storyboard Post-Acceptance Recovery Evidence

- Authorization: `FTG-0-20260720-001`
- Recovery work item: `FT-03-002R`
- Recovered work item: `FT-03-002`
- Workline: `codex-03`
- Branch: `ft/codex-03-storyboard`
- Surviving baseline: `3d862bf24d3f1c09bbffd5ca6becd5f6de28d340`
- Recovery date: `2026-07-23`
- Recovery write probe: `PASS`
- Network/Provider/credential access: `0`

## Recovery result

The eight rescued pre-surgery disassemblies were compared with their `3d862bf` current-state counterparts. Disassembly address noise and unordered `frozenset` rendering were normalized. The three pytest-rewritten test caches were also regenerated in memory with Python `3.14.0` and pytest `9.1.1` before recursive code-object comparison.

All eight current source files already compile to the rescued pre-surgery bytecode exactly, including nested code objects, constants, names, line tables, exception tables, assertion operands, and assertion messages. Therefore no Python source rewrite was required or introduced:

- `src/ai_video_platform/skills/storyboard/cli.py`
- `src/ai_video_platform/skills/storyboard/domain.py`
- `src/ai_video_platform/skills/storyboard/interface.py`
- `src/ai_video_platform/skills/storyboard/planning.py`
- `tests/skills/storyboard/test_storyboard_continuity.py`
- `tests/skills/storyboard/test_storyboard_failures.py`
- `tests/skills/storyboard/test_storyboard_features.py`
- `tests/skills/storyboard/test_storyboard_interface.py`

The destroyed evidence increment is restored by this document. No Contract, Core module, other Skill, Legacy source, Provider adapter, or shared surface was modified.

## Fresh verification

All commands ran under Python `3.14.0` with `PYTHONPATH` absent and no network access.

- Storyboard owner suite: `45 tests`, `9/9 subtests`, `OK`.
- Affected Storyboard plus image-panel/video-planning consumers: `84 tests`, `OK`.
- Contracts guard: `47 tests`, `9/9 subtests`, `OK`.
- Architecture guard: `28 tests`, `OK`.
- Security guard: `10 tests`, `2/2 subtests`, `OK`.
- Full offline runner: `311 tests`, `OK`, `skipped=3` because symlink creation is unavailable on the Windows host.

## Rollback

Use a normal `git revert` of the recovery commit and rerun the Storyboard owner suite plus `py -3.14 tools\run_offline_tests.py`. Do not reset the branch, alter repository bookkeeping, delete immutable artifacts, or change shared surfaces.
