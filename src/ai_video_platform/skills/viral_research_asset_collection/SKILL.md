# Viral Research & Asset Collection

Version: `0.1.0-rc.offline`

This Skill validates viral-research requests, expands queries, normalizes and deduplicates fake Provider results, produces explainable rankings, enforces rights/PII/expiry policy, plans selected-reference collection, and writes controlled Research Library metadata. It does not write Product Library, analyze selected references, call a real Provider, download real media, publish unregistered business artifacts, or read Legacy paths.

## Public commands

- `inspect-research-request`: validates all inputs without side effects.
- `research-viral`: performs the offline research flow using only the exact built-in fake or rejecting Provider type.
- `collect-reference-assets`: collects selected metadata using only the exact built-in fake or rejecting downloader type.

Each command accepts `--input <json-file>` and optional `--now <UTC-Z>`, prints one JSON result, and returns `0` on success or `2` for a stable redacted error.

## Inputs, outputs, and boundaries

Requests explicitly include platform, market, region, time window/expiry, campaign goal, audience, format, bounded search budget, guarded download policy, seed queries, and idempotency key. Outputs are local immutable Skill results, not `ViralResearchPack` or `ReferenceCollectionManifest`; those cross-Skill artifacts remain blocked until Codex-00 registers them in the separate Business Artifact Registry. Foundation Registry remains 1 Envelope + 11 payload IDs.

Hard ceilings are `max_queries=50`, `max_results=500`, `max_provider_calls=10`, and `timeout_seconds=60`. A score records every factor's normalized input, weight, weighted contribution, and summed total.

Only this Skill's controlled storage seam may write Research Library metadata. The filesystem adapter requires an explicit root and tests use temporary roots only. Unknown rights become metadata-only; PII/unsafe material is quarantined; expired material stays expired. Retention cannot be silently extended and deletion is audited.

## Failure, retry, cancellation, and safety

Validation precedes external side effects. A request claim is recorded before Provider or download work; exact completed replays return the stored result without repeating calls, conflicting or concurrent key reuse fails closed, and failed attempts release their claim. Provider retries are limited to two and remain inside the request's total provider-call budget. Cancellation is checked before and during work. Errors are stable and redact secret-like fields. Real Provider/network/media/credential paths are unavailable; exact built-in fake and rejecting adapter types are the only adapters accepted in this release candidate.

Stable codes include validation, budget, expiry, cancellation, idempotency conflict, Provider forbidden/failure, download forbidden, path forbidden, rights forbidden, storage conflict, and retention-extension forbidden. Example Hermes call: `python -m ai_video_platform.skills.viral_research_asset_collection inspect-research-request --input request.json`; consume the JSON status and never import an adapter.

## Tests and operations

Run the three owned unittest modules from the task card, then `python tools\run_offline_tests.py`. Rollback is the owning branch commit revert; real seams remain fail-closed. Hermes may call only the three public commands and must not import adapters. Maintainer: `codex-02`; authorization: `FTG-0-20260720-001`; Provider smoke: `NOT_AUTHORIZED`.
