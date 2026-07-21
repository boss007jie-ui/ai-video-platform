# Dependency Change Request: Offline Coverage Evidence

- authorization_id: `FTG-0-20260720-001`
- work_item_id: `FT-01-001`
- requester: `codex-01`
- owner/implementer: `codex-00`
- status: `REQUESTED`

## Need

`PRODUCTION_READY_DEFINITION.md` requires line and branch coverage evidence. The common baseline has no coverage runner (`python -m coverage --version` fails with `No module named coverage`), and Codex-01 cannot modify `pyproject.toml` or lock files.

## Requested decision

Provide an approved, pinned, offline-available coverage tool and integration command, preferably `coverage.py` with branch measurement, or designate existing Codex-00 release tooling that produces equivalent line/branch evidence.

## Constraints

- No network install from this workline.
- Codex-00 alone updates dependency metadata/locks and shared release tooling.
- Tooling must run under the process-wide network deny guard.
- No Provider, Legacy, credential, or real Product Library access.

## Evidence currently available

All public commands, stable owned errors, high-risk publication/approval/concurrency/recovery branches have direct behavior tests. Numeric line/branch percentages remain pending this request.
