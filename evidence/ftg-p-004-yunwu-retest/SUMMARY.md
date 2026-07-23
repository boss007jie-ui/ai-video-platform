# FTG-P-004 Yunwu dual-model retest

- Task: `FT-04-YUNWU-SMOKE`
- Authorization: `FTG-P-004` (parent `FTG-0-20260720-001`)
- Verdict: `COMPLETE_WITH_GAPS`
- Size gate: added in `6d2dc52`
- Execution: serial, one attempt per model, `retries: 0`
- Requested size: `1024x1024`
- Key scan: 0 exact-key hits; 0 evidence secret-pattern hits

| Adapter | Result | HTTP | Elapsed | Received | Bytes | SHA-256 |
|---|---|---:|---:|---:|---:|---|
| `yunwu-nano-banana` | PASS | 200 | 29608 ms | 1024x1024 | 996238 | `369c7b3d5610c932e499ab26b302e9f1641a16f243cf2e24615c7c78ea591b29` |
| `yunwu-image2` | FAIL | 200 | 45730 ms | 1254x1254 | 1424589 | `97c2be5d78bb15f41dea7e63eaf052d0af00b19bea3d9c11634074191e05067b` |

## Findings

nano-banana returned a valid PNG at the requested size. The persisted artifact was independently reopened with Pillow; its dimensions, byte count, and SHA-256 match the Provider and artifact receipts.

image2 returned HTTP 200 but decoded to 1254x1254 rather than 1024x1024. The fail-closed gate marked the model FAIL and did not persist a success artifact. The adapter recorded the decoded response dimensions, byte count, SHA-256, HTTP status, elapsed time, and Provider usage before rejecting the result.

## Evidence

- `receipts/nano-banana-receipt.json`: Provider and artifact receipt
- `receipts/nano-banana-verification.json`: independent persisted PNG verification
- `receipts/image2-receipt.json`: fail-closed Provider receipt
- `receipts/image2-verification.json`: received-size verification and no-artifact record
- `receipts/*-cli.json`: sanitized CLI outcomes
