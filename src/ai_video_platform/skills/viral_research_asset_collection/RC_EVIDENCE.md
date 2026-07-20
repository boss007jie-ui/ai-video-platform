# Viral Research & Asset Collection — Offline RC Evidence

## Identity and status

- Authorization: `FTG-0-20260720-001`
- Work item: `FT-02-001`
- Branch: `ft/codex-02-research-reference`
- Evidence head: `c6505f8`
- Status: `RC_PROVIDER_PENDING`
- Production Ready: **not claimed**
- Provenance: `CLEAN_ROOM_ONLY`; no Legacy source was read, copied, tested or adopted

The public local interfaces are `inspect_research_request`, `research_viral`, and `collect_reference_assets`. The approved external Business Artifact Registry identities and SemVer schemas remain a Codex-00 change request, so this RC must not be integrated as a final shared contract implementation yet.

## Implemented offline behavior

- deterministic query expansion, request/time-window/budget validation and cancellation;
- candidate normalization plus independent source, URL, exact-content and near-duplicate controls;
- explainable ten-factor ranking with inputs, weights and contributions;
- rights, PII, brand-safety, expiry, quarantine and `METADATA_ONLY` decisions;
- fake/rejecting Provider and Download seams with capped retry behavior;
- in-memory and filesystem Research Library metadata adapters;
- atomic no-clobber writes, durable idempotency/audit/index repair, retention and deletion audit;
- traversal, absolute path, symlink/junction/dangling-link guards where the host supports creating links;
- recursive public-error and bearer/token redaction;
- independent CLI and `SKILL.md`.

No Product Library was created or written. Tests use temporary directories only; no authorized real Research Library root was populated.

## Fresh verification at evidence head

| Command | Result |
|---|---|
| `python -m unittest -v tests.skills.viral_research_asset_collection.test_viral_research_interface` | PASS — 6/6, 0.011s |
| `python -m unittest -v tests.skills.viral_research_asset_collection.test_research_library_adapters` | PASS — 4 passed, 2 host-capability skips, 0.183s |
| `python -m unittest -v tests.skills.viral_research_asset_collection.test_provider_download_guards` | PASS — 4/4, 0.001s |
| `python tools\run_offline_tests.py` | BLOCKED SHARED BASELINE — 82 passed, 3 host-capability skips, 1 stale placeholder-only assertion; 86 total, 0.812s |

The three skips are Windows environments where symlink creation is unavailable; the implementation still rejects links when present and the two Viral link tests fail closed when the capability exists. No line-coverage tool or new dependency was introduced, so a coverage percentage is not claimed. The focused acceptance surface contains 16 tests.

## Security, dependency and operations evidence

- Real Provider, Apify, media download and network smoke: `NOT_AUTHORIZED` and not run.
- Credential values: not read, displayed, copied or tested.
- Runtime dependencies in this Skill: Python standard library and local Skill modules only; no package/lock change.
- Repository secret scan, Legacy-root guard, network/subprocess guards and rejecting-provider baseline tests pass in the complete suite.
- Performance evidence is bounded offline unit execution only; no production throughput/SLA claim.
- Rollback: Codex-00 can omit or revert commits `173657c`, `198be8b`, and `d308414`; the branch creates no production data migration.

## Open gates

1. Codex-00 approval and publication of the three requested Business Artifact Registry contracts.
2. Codex-00 decision on the optional Apify adapter dependency.
3. Separate `FTG-P` before any real Provider/download smoke.
4. Codex-00 update of the shared placeholder-only architecture test.
5. Windows/link-capable CI execution of the skipped symlink/junction cases.

Next gate requested: `FTG-2` for shared contract/dependency review; `FTG-P` is explicitly not requested for execution by this evidence file.
