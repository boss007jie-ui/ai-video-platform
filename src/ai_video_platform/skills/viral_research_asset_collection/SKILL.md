# Viral Research & Asset Collection

Version: `0.1.0-rc.provider-pending`

This Skill validates viral-research requests, expands queries, normalizes and deduplicates Provider results, produces explainable rankings, enforces rights/PII/expiry policy, plans selected-reference collection, and writes controlled Research Library metadata. Under `FTG-P-RESEARCH-001`, an Apify TikTok collection adapter is available only by explicit injection for the authorized metadata-only smoke. It does not write Product Library, analyze selected references, download real media, publish unregistered business artifacts, or read Legacy paths.

## Public commands

- `inspect-research-request`: validates all inputs without side effects.
- `research-viral`: defaults to the rejecting Provider; the authorized Apify path requires every explicit flag described below.
- `collect-reference-assets`: collects selected metadata using only the exact built-in fake or rejecting downloader type.

Each command accepts `--input <json-file>` and optional `--now <UTC-Z>`, prints one JSON result, and returns `0` on success or `2` for a stable redacted error. No command silently selects a real adapter.

The authorized Provider invocation is `research-viral --provider apify --authorization-id FTG-P-RESEARCH-001 --library-root <explicit-controlled-root>`. It resolves the credential only from the `APIFY_API_KEY` process environment variable. The request must be TikTok/US, metadata-only, use two or three seed queries, zero retries, one Provider call, and 10–20 results. The adapter starts exactly one Actor run, refuses redirects, caps charged results at 20 and total charge at USD 0.01, then reads metadata once. Direct public media download is separately authorized with `collect-reference-assets --authorization-id FTG-P-RESEARCH-002 --library-root <explicit-controlled-root>` and requires candidate digest, source URL and expiry to match the normalized ledger exactly; the public CDN URL is allowlisted and, when retained by the ledger, must also match exactly. It uses one GET-only/no-redirect session, allows at most three successes/five attempts, and enforces 40 MB per file and 100 MB total. Default behavior remains fail-closed.

## Inputs, outputs, and boundaries

Requests explicitly include platform, market, region, time window/expiry, campaign goal, audience, format, bounded search budget, guarded download policy, seed queries, and idempotency key. Outputs are local immutable Skill results, not `ViralResearchPack` or `ReferenceCollectionManifest`; those cross-Skill artifacts remain blocked until Codex-00 registers them in the separate Business Artifact Registry. Foundation Registry remains 1 Envelope + 11 payload IDs.

Hard ceilings are `max_queries=50`, `max_results=500`, `max_provider_calls=10`, and `timeout_seconds=60`. A score records every factor's normalized input, weight, weighted contribution, and summed total.

Only this Skill's controlled storage seam may write Research Library metadata. The filesystem adapter requires an explicit root and tests use temporary roots only. Unknown rights become metadata-only; PII/unsafe material is quarantined; expired material stays expired. Retention cannot be silently extended and deletion is audited.

## Failure, retry, cancellation, and safety

Validation precedes external side effects. A request claim is recorded before Provider or download work; exact completed replays return the stored result without repeating calls, conflicting or concurrent key reuse fails closed, and failed attempts release their claim. Provider retries are limited to two and remain inside the request's total provider-call budget; the authorized Apify smoke requires zero retries and a single-use adapter. Cancellation is checked before and during work. Errors are stable and recursively redact secret-like fields. The Apify bearer credential never appears in URLs, outputs, receipts, errors, or `repr`, and redirects are refused. Media success and failure receipts are atomically written as UTF-8 before caller output; failed or expired URLs advance to the next ledgered candidate without retry, successful replay verifies file size and digest, and candidate deletion removes its media and receipt. Assets remain `internal_analysis_only` with `rights_status=UNKNOWN`.

Stable codes include validation, budget, expiry, cancellation, idempotency conflict, Provider forbidden/failure, download forbidden, path forbidden, rights forbidden, storage conflict, and retention-extension forbidden. Example Hermes call: `python -m ai_video_platform.skills.viral_research_asset_collection inspect-research-request --input request.json`; consume the JSON status and never import an adapter.

## Tests and operations

Run the four owned unittest modules, including `test_apify_adapters`, then `python tools\run_offline_tests.py`. Rollback is the owning branch commit revert; default Provider and all media seams remain fail-closed. Hermes may call only the three public commands and must not import adapters. Maintainer: `codex-02`; implementation authorization: `FTG-P-RESEARCH-001`; Provider smoke status is recorded in `RC_EVIDENCE.md`.
