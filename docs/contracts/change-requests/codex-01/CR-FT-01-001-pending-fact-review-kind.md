# Contract Change Request: ProductReviewContext `pending_fact`

- authorization_id: `FTG-0-20260720-001`
- work_item_id: `FT-01-001`
- requester: `codex-01`
- owner/implementer: `codex-00`
- status: `REQUESTED`

## Problem

The approved Product Knowledge design requires pending facts in `ProductReviewContext`. Foundation validation currently allows `pending_feedback`, `fact_conflict`, `asset_confirmation`, `inferred_fact`, and `identity_ambiguity`, but has no exact kind for a non-inferred fact awaiting confirmation.

## Requested additive change

Add `pending_fact` to the allowed `review_items[].kind` values for `avp.contract.product-review-context`, with synthetic valid/invalid/compatibility fixtures and no Foundation identity change. Foundation Registry must remain one Envelope plus eleven payload IDs.

## Current fail-closed compatibility behavior

Until Codex-00 decides this request, the owned implementation maps a non-conflicting fact candidate awaiting confirmation to the closest existing review-only kind, `inferred_fact`. It never enters `ProductContextBundle`. This is explicitly a temporary representation, not a new Contract identity or alias.

## Acceptance

- Existing 1+11 identity set unchanged.
- `pending_fact` accepted only in `ProductReviewContext`.
- Confirmed/effective facts remain forbidden in review context.
- Generated schemas/fixtures and compatibility tests remain reproducible.
