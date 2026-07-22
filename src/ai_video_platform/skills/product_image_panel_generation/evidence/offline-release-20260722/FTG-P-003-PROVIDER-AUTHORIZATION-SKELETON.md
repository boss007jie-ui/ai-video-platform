# FTG-P-003 Provider Authorization Skeleton

Status: `UNSIGNED_TBD`
Authorization parent: `FTG-0-20260720-001`
Target workline: `Codex-04 / product-image-panel-generation`
Prepared: `2026-07-22`

This is a fill-in skeleton, not an authorization, Adoption Manifest, Provider selection, or permission to run a smoke test. Every `TBD_BY_HERMES_AFTER_USER_DECISION` value must be completed by Hermes after the user selects a Provider, then independently reviewed and signed before any real Adapter, SDK, endpoint, credential access, network request, or generated image is permitted.

## Provider decision

| Field | Required value |
|---|---|
| Provider legal/display name | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Provider adapter identifier | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Approved model identifiers and versions | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Data-processing region | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Terms/privacy review reference | `TBD_BY_HERMES_AFTER_USER_DECISION` |

## Endpoint boundary

| Field | Required value |
|---|---|
| Exact approved endpoint host/path allowlist | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| HTTP method(s) | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| TLS and certificate requirements | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Redirect policy | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Timeout and retry ceiling | `TBD_BY_HERMES_AFTER_USER_DECISION` |

No wildcard endpoint, redirect expansion, discovery endpoint, arbitrary URL input, upload URL, or download URL is implicitly authorized.

## Billing and quota boundary

| Field | Required value |
|---|---|
| Billing unit and price source | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Per-attempt maximum cost | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Per-request maximum cost | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Daily/project quota | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Concurrency ceiling | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Kill-switch owner and procedure | `TBD_BY_HERMES_AFTER_USER_DECISION` |

## Input and output constraints

| Field | Required value |
|---|---|
| Allowed dimensions/aspect ratios | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Allowed input media types and byte limits | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Prompt/content policy reference | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Reference-image rights requirements | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Output media types and byte limits | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Retention/deletion policy | `TBD_BY_HERMES_AFTER_USER_DECISION` |

## Credential handling placeholders

- Credential mechanism and secret-store reference: `TBD_BY_HERMES_AFTER_USER_DECISION`.
- Credential owner/rotation/revocation process: `TBD_BY_HERMES_AFTER_USER_DECISION`.
- Credential values, tokens, headers, and environment contents must never be entered in this card or its evidence.
- A signed card may authorize a named retrieval mechanism; it must not disclose a credential value.

## Bounded Provider smoke proposal

| Field | Required value |
|---|---|
| Smoke authorization ID | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Maximum calls | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Maximum billed amount | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Sanitized input fixture | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Redacted evidence destination | `TBD_BY_HERMES_AFTER_USER_DECISION` |
| Abort conditions | `TBD_BY_HERMES_AFTER_USER_DECISION` |

Current Provider smoke disposition: `NOT_AUTHORIZED`.

## Required approvals

- User Provider decision: `PENDING`.
- Hermes scope completion: `PENDING`.
- Security/privacy review: `PENDING`.
- Cost/quota review: `PENDING`.
- FTG-P-003 signature: `PENDING`.

Until all required approvals are complete, the only allowed runtime adapters remain `fake` and `rejecting`, with `rejecting` as the CLI default.
