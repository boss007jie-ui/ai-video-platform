# Product Image / Panel Offline Release Record

Authorization: `FTG-0-20260720-001`
Work item: `FT-04-001`
Branch: `ft/codex-04-image-panel`
Worktree: `C:\Users\boss0\Desktop\05-项目文件夹\AI Video Platform\.worktrees\codex-04-image-panel`
Recorded: `2026-07-22T16:58:16+08:00`

## Release decision

- Product Image / Panel offline capability: `INTERNAL_PRODUCTION_READY_OFFLINE`.
- Real image Provider path: `RC_PROVIDER_PENDING`.
- Full Production Ready: `NOT_CLAIMED`.
- Provider smoke: `NOT_AUTHORIZED`.
- Provider selection, network calls, credential access, Provider SDK installation, binary media generation, and real endpoints: not performed.

The independently releasable surface is preflight, deterministic prompt compilation, explicit Fake generation, default Rejecting fail-closed behavior, task-local result accounting, and exact ledger replay. The CLI adapter allowlist remains exactly `fake` and `rejecting` and defaults to `rejecting`.

## Exact release point and commits

The source and shared-guard synchronization verified by this record is:

`9ab2bcad14526d223327248d3d5619c3a6c9ba0c` — merge of the then-current `ft/codex-00-integration` into this workline, zero conflicts.

Closeout commits included at that release point:

| Commit | Purpose |
|---|---|
| `b4141feb05393d430cc400c9af7b519c290499e7` | approved closeout design |
| `62a36179d83a205b0cb68d7601ac31b38112d385` | design corrections for AST guard and runtime |
| `c0ac5be06d85a2e06600dca6a19274854e2b10c0` | implementation plan |
| `4663f80608e8a1ed9e53a87785410c41f8804776` | `ImageProviderAdapter` ABC, inherited public fail-closed entrypoint, service admission |
| `17ed270dd2817608789a8fa9a7437f33acce3259` | production `_generate` call-site AST guard |
| `fc09fc2185a72a7040ddc8385d11f350d179eeaa` | CLI adapter allowlist characterization |
| `74ac3e8fafaf0b6111622dc0bdcdcf9daffbdad7` | two sanitized request documents |
| `67ce2203de4a3c0cf4c776fd300453dfe6dccd55` | initial actual CLI receipts |
| `f5a74c07bcb6808d7eb4b8471bf2648c404fb80f` | operations record, static/runtime evidence, unsigned Provider gate skeleton |

The evidence-only commit containing the refreshed post-sync logs and this record is reported as the final commit in the accompanying `hermes_status`; it does not change the runtime release point above.

## Adapter contract and architecture evidence

- `ImageProviderAdapter` is an ABC; an incomplete Adapter raises `TypeError` at instantiation.
- Subclasses cannot override public `generate()`; inherited calls always raise `IMAGE_PANEL_PROVIDER_BYPASS_FORBIDDEN`.
- `_generate` is documented as an internal Python convention, not a security or authorization boundary.
- The owned AST guard scans all production modules and permits `_generate` calls only in this Skill's `service.py` and `adapters.py`.
- Synthetic architecture cases prove both a direct call in `rogue.py` and an aliased method access in `alias.py` are detected.
- Normal service execution invokes the Fake seam once. Exact replay leaves total Adapter invocations at one (`delta=0`).

## Sanitized CLI receipts

All four commands were rerun after integration synchronization with `PYTHONPATH=src` and Python 3.14.0. Exact command strings, exit codes, output hashes, and replay counts are in `receipt-manifest.json`.

| Stage | Exit | Result | Raw stdout |
|---|---:|---|---|
| inspect | 0 | approved | `01-inspect.stdout.json` |
| Fake generate | 0 | completed, attempts=1 | `02-fake.stdout.json` |
| exact replay | 0 | replayed=true, cumulative attempts=1 | `03-replay.stdout.json` |
| default Rejecting | 3 | failed closed with `IMAGE_PANEL_PROVIDER_NOT_AUTHORIZED` | `04-rejecting.stdout.json` |

Ledger receipt: `ledger-receipt.json`, two records, SHA-256 recorded in `receipt-manifest.json`. No image bytes are stored in evidence; the Fake asset is represented only by deterministic metadata and a `memory://offline/...` URI.

## Fresh post-sync verification

Every test command cleared `PYTHONPATH` and ran in the current worktree after commit `9ab2bcad14526d223327248d3d5619c3a6c9ba0c`. The final raw logs were captured through `cmd.exe` so Python's unittest stderr is preserved without PowerShell error-object formatting.

| Exact command | Result | Absolute log path |
|---|---|---|
| `cmd.exe /d /c "set PYTHONPATH=&& py -3.14 -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_interface > src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\10-interface-tests.log 2>&1"` | `Ran 22 tests`, `OK` | `C:\Users\boss0\Desktop\05-项目文件夹\AI Video Platform\.worktrees\codex-04-image-panel\src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\10-interface-tests.log` |
| `cmd.exe /d /c "set PYTHONPATH=&& py -3.14 -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_adapters > src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\11-adapters-tests.log 2>&1"` | `Ran 15 tests`, `OK` | `C:\Users\boss0\Desktop\05-项目文件夹\AI Video Platform\.worktrees\codex-04-image-panel\src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\11-adapters-tests.log` |
| `cmd.exe /d /c "set PYTHONPATH=&& py -3.14 -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_safety > src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\12-safety-tests.log 2>&1"` | `Ran 18 tests`, `OK` | `C:\Users\boss0\Desktop\05-项目文件夹\AI Video Platform\.worktrees\codex-04-image-panel\src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\12-safety-tests.log` |
| `cmd.exe /d /c "set PYTHONPATH=&& py -3.14 -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_architecture > src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\13-architecture-tests.log 2>&1"` | `Ran 3 tests`, `OK` | `C:\Users\boss0\Desktop\05-项目文件夹\AI Video Platform\.worktrees\codex-04-image-panel\src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\13-architecture-tests.log` |
| `cmd.exe /d /c "set PYTHONPATH=&& py -3.14 tools\run_offline_tests.py > src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\14-offline-full-tests.log 2>&1"` | `Ran 310 tests`, `OK (skipped=3)` | `C:\Users\boss0\Desktop\05-项目文件夹\AI Video Platform\.worktrees\codex-04-image-panel\src\ai_video_platform\skills\product_image_panel_generation\evidence\offline-release-20260722\14-offline-full-tests.log` |

The three skips are platform-conditional symlink tests reporting that symlink creation is unavailable; they are not failures or Provider tests.

## Runtime and static evidence

- Project metadata remains `requires-python = ">=3.12"` and was not modified.
- Verification runtime: `Python 3.14.0`.
- Python 3.12: `NOT_RUN_ENVIRONMENT_UNAVAILABLE_USER_DIRECTED_LOCAL_3_14`.
- Runtime evidence: `16-python-runtime.log` and `python-runtime.txt`.
- Post-sync static scan: no Provider/network SDK imports, credential access, real endpoint literal, or binary media; see `15-static-scan.log` and `static-scan.txt`.
- Foundation Registry guard remains one Envelope plus exactly eleven payload IDs and is covered by the full suite.

## Rollback and kill switch

Immediate operational kill switch: omit `--adapter fake` and use the default `RejectingImageProviderAdapter`. This performs no Provider or network side effect.

Runtime contract rollback command:

```powershell
git revert 4663f80608e8a1ed9e53a87785410c41f8804776
```

That commit contains the only production-code change in this closeout together with its contract tests. Evidence/doc/test-only commits may be reverted separately in reverse order if the release record itself must be withdrawn. Do not revert the `9ab2bcad...` integration merge as an image-panel rollback: it is the shared-guard synchronization prerequisite, not a Provider capability change.

No database migration, remote resource, credential, real task media, Provider asset, or external side effect requires reversal.

## Remaining Provider gate

`FTG-P-003-PROVIDER-AUTHORIZATION-SKELETON.md` remains unsigned with every Provider-specific field set to `TBD_BY_HERMES_AFTER_USER_DECISION`. A user Provider decision, completed endpoint/billing/quota/input constraints, credential mechanism approval, signed FTG-P-003, and separately bounded Provider smoke are still required before any real Provider path can move beyond `RC_PROVIDER_PENDING`.
