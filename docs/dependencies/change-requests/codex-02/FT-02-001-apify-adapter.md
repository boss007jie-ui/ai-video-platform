# FT-02-001 Apify Adapter Decision and Media Follow-up

- Requester: `codex-02`
- Authorization: `FTG-P-RESEARCH-001`
- Work item: `FT-02-001`
- Owner requested: `codex-00`
- Status: `COLLECTION_RESOLVED_MEDIA_PENDING`
- Provider gate: metadata-only collection authorized; media download not authorized

## Decision requested

Hermes selected `apidojo/tiktok-scraper` for the bounded metadata-only research smoke. Codex-02 implemented the collection adapter with the Python standard library, so no package or lockfile dependency is introduced. Default CLI behavior remains rejecting and the real path requires explicit authorization, explicit controlled storage root and an environment credential.

The remaining media-download decision requires a separate authorization and must define:

- the authorized media URL/receipt fields, which are not part of the current safe research candidate;
- whether bytes come from an Apify dataset field or a separate Provider endpoint;
- content-type, byte-size, redirect, host and checksum constraints;
- download count/cost budgets, timeout, cancellation and kill-switch behavior;
- rights eligibility and quarantine behavior before any byte transfer;
- the exact future authorization ID accepted by the downloader gate.

## Mandatory runtime gate

The collection adapter accepts only `FTG-P-RESEARCH-001` and is single-use. The staged downloader always rejects; implementing and enabling real media transfer remains blocked until the follow-up authorization defines the above contract. No current CLI path can select a real downloader.

## Acceptance and rollback

Collection acceptance requires mocked HTTP tests, environment-only credential resolution, fixed-origin/no-redirect transport, capped cost/results, stable redaction and no import-time network side effect. Rollback reverts the final Codex-02 provider commit while preserving fake/rejecting seams; no schema or stored-artifact migration is required.
