# Codex-00 Integration Change Request — FT-05-002

- Authorization: `FTG-0-20260720-001`
- Work item: `FT-05-002`
- Requesting workline: Codex-05 / `ft/codex-05-planning-video`
- Owner required: Codex-00
- Status: `OPEN`

## Requested shared-guard change

After merging the Codex-05 FT-05-002 commit, add `"video_enhancement"` to the
`SKILL_NAMES` set in `tests/architecture/test_clean_room_boundaries.py`.

Codex-05 did not edit that shared architecture test. The fresh full offline run
executed 349 tests: its sole failure was
`CleanRoomBoundaryTests.test_business_namespaces_are_ft1_skill_packages`, because
the newly authorized owner package exists but the shared allowlist still contains
only the original eight skill names. All 17 FT-05-002 owned tests passed.

## Acceptance

```text
$env:PYTHONPATH=$null
py -3.14 tools\run_offline_tests.py
```

Expected: the namespace equality includes the nine authorized skill packages and
the full suite is green. This request does not ask Codex-00 to alter the Foundation
Registry; it remains one Envelope plus eleven payload IDs.
