# Viral Research & Asset Collection - Provider RC Evidence

## Identity and status

- Base authorization: `FTG-0-20260720-001`
- Provider authorization: `FTG-P-RESEARCH-001`
- Work item: `FT-02-001`
- Branch: `ft/codex-02-research-reference`
- Synchronized base head: `56bf2ab30f2048f9da8aa2c466de4e934fb99878`
- Final implementation commit: reported in the Hermes handoff after commit
- Status: `RC_PROVIDER_PENDING`
- Production Ready: **not claimed**
- Provenance: `CLEAN_ROOM_ONLY`; no Legacy source was read, copied, tested or adopted

The public local interfaces are `inspect_research_request`, `research_viral`, and `collect_reference_assets`. The approved external Business Artifact Registry identities and SemVer schemas remain a Codex-00 change request, so this RC must not be integrated as a final shared contract implementation yet.

## Implemented behavior

- deterministic query expansion, request/time-window/budget validation and cancellation;
- candidate normalization plus independent source, URL, exact-content and near-duplicate controls;
- explainable ten-factor ranking with inputs, weights and contributions;
- rights, PII, brand-safety, expiry, quarantine and `METADATA_ONLY` decisions;
- exact-type allowlisting for built-in fake/rejecting seams plus the explicitly authorized Apify collection adapter;
- environment-only credential resolution, bearer-header authentication, fixed Apify origin and redirect refusal;
- one Actor run per adapter, one dataset read, zero-retry smoke policy, 20-result and USD 0.01 charge caps;
- safe TikTok metadata normalization with unknown rights, PII/title screening, brand-safety quarantine and seven-day expiry;
- machine-readable run ID, returned count, actual cost, charged events, per-seed hit counts and ranking decomposition;
- request claims before Provider/download work, durable completed replay and conflict rejection;
- in-memory and filesystem Research Library metadata adapters;
- atomic no-clobber writes, per-source cross-process locking across metadata/quarantine, immutable source IDs, durable audit/index repair, retention and deletion audit;
- traversal, absolute path, symlink/junction/dangling-link guards where the host supports creating links;
- recursive public-error and bearer/token redaction;
- independent CLI and `SKILL.md`.

No Product Library was created or written. Tests use temporary directories only; no authorized real Research Library root was populated.

## Fresh offline verification

| Command | Result |
|---|---|
| `py -3.14 -m unittest tests.skills.viral_research_asset_collection.test_apify_adapters` with `PYTHONPATH` unset | PASS - 9/9 |
| `py -3.14 -m unittest tests.skills.viral_research_asset_collection.test_apify_adapters tests.skills.viral_research_asset_collection.test_viral_research_interface tests.skills.viral_research_asset_collection.test_research_library_adapters tests.skills.viral_research_asset_collection.test_provider_download_guards` with `PYTHONPATH` unset | PASS - 31 run, 2 host-capability skips |
| `py -3.14 tools\run_offline_tests.py` with `PYTHONPATH` unset | PASS - 113 passed, 3 host-capability skips |

The skips are Windows environments where symlink creation is unavailable; the implementation rejects links when present. No line-coverage tool or new dependency was introduced, so a coverage percentage is not claimed. The focused Viral acceptance surface contains 31 tests.

## Security, dependency and operations evidence

- Real Apify metadata smoke: one authorized single-call attempt was executed under `FTG-P-RESEARCH-001` with three TikTok US seeds, `max_provider_calls=1`, `max_results=20`, `maxTotalChargeUsd=0.01`, zero retries and `METADATA_ONLY`. The Research Library request ledger proves `COMPLETED`, `provider_calls=1`, `partial=true`, 19 deduplicated metadata candidates, zero media downloads and zero Product Library writes.
- The CLI process failed while serializing non-ASCII Provider output to the Windows console after the Provider work completed; `smoke-output.log` is empty. The receipt was subsequently reconciled with read-only Apify GET requests, without rerunning the Actor. The UTF-8 stdout fix and regression test are included in this commit.
- Reconciled receipt: actor run `PLpc5eSso79mdBouE`, status `SUCCEEDED`, dataset `tbKOF4BafGbvUzkBC`, started `2026-07-22T02:42:59.436Z`, finished `2026-07-22T02:43:35.987Z`, `usageTotalUsd=0.005999999999999999` (USD 0.006), `chargedEventCounts={"apify-default-dataset-item":20}`. Dataset GET returned 20 items.
- Reconciled per-seed hit counts: `laser pointer tactical EDC=19`, `laser pointer gear review=1`, `laser pointer everyday carry=0`, `unattributed=0`.
- Idempotent replay was run locally without a second Provider call: `status=IDEMPOTENT_REPLAY`, `provider_call_performed=false`, `deduped_count=19`; full ranking decomposition is retained in `C:\tmp\FT-02-001-apify-smoke-20260722\idempotent-replay.json`.
- Research Library contents after smoke: 19 `metadata/*.json`, 0 quarantine files, 1 request ledger, `audit/idempotency.json`, `audit/lifecycle.jsonl`, and `audit/lifecycle-index.json`; all candidates are `metadata_only` with `rights_status=UNKNOWN`.
- Credential presence evidence is only `APIFY_API_KEY_PRESENT=True`; a scan of smoke artifacts and the Research Library found `SECRET_PATTERN_HIT_COUNT=0`. No credential value was printed or persisted.
- Real media download and `collect-reference-assets` Provider execution: `NOT_AUTHORIZED` and not run.
- Credential values: never displayed, copied, stored in artifacts, or placed in URLs; owned tests use an explicitly synthetic value. The authorized smoke's presence-only artifact is `C:\tmp\FT-02-001-apify-smoke-20260722\credential-presence.log`.
- Arbitrary Python adapter injection fails before calls; default CLI remains rejecting.
- Runtime dependencies in this Skill: Python standard library and local Skill modules only; no package/lock change.
- Repository secret scan, Legacy-root guard, network/subprocess guards and rejecting-provider baseline tests pass in the complete suite.
- Performance evidence is bounded offline unit execution only; no production throughput/SLA claim.
- Rollback: Codex-00 can omit or revert the final provider implementation commit reported in the Hermes handoff; no real Provider run or production data migration has occurred.

## Open gates

1. Issue a separate media-download authorization and define the permitted media receipt/input contract before enabling the staged Apify downloader.
2. Windows/link-capable CI execution of the skipped symlink/junction cases.

Next gate requested: media-download authorization and shared-contract/adoption review; Provider smoke is reconciled and PASS, while overall status remains `RC_PROVIDER_PENDING`.
