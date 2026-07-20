# FT-06-001 QA / Review RC Evidence

Status: `REVIEW_BLOCKED_DEPENDENCY`
Authorization: `FTG-0-20260720-001`
Workline: `codex-06`
Provider smoke: `NOT_REQUIRED`

## Implemented evidence

- Public Interface and four independent commands at `1.0.0`.
- Stable, sanitized errors and deterministic `pass` / `fail` / `needs-review` outcomes.
- Contract, asset approval, product/SKU identity, continuity, drift, quality, stale input,
  partial failure, cancellation, and recovery behavior.
- Structured human review package with versioned criteria and evaluation set.
- Outputs restricted to `ReviewDecision`, `FeedbackEvent`, QA artifact, and
  `SkillExecutionEvent`; no approval or Product Library/context writer exists.
- Reference Analysis semantic comparison criteria are rejected.
- Atomic allowlisted task-output writer; Product/Research Library and Legacy targets reject.
- Offline synthetic fixtures only; no network, Provider, credential, media download, Legacy
  runtime path, adoption, or Library mutation.

## Locked evaluation set

`fixtures/golden/qa_review/evaluation-v1.json` locks:

- maximum false-positive rate: `0.0`;
- maximum false-negative rate: `0.0`;
- maximum needs-review rate: `0.34`.

Current deterministic result is 0% false positive, 0% false negative, and 25%
needs-review across four synthetic cases.

## Verification snapshot

| Suite | Result |
|---|---|
| QA Interface | 5 tests, OK |
| QA permissions | 6 tests, OK |
| QA evaluation | 2 tests, OK |
| Integration acceptance | 2 tests, OK |
| Golden | 2 tests, OK |
| Full offline | 75 run; 74 pass; 1 Codex-00-owned baseline guard failure |
| Foundation registry | exact 1 Envelope + 11 payload IDs, PASS |
| Secret/network/legacy/provider guards | PASS |
| Offline reproducible wheel | PASS |

The full-suite failure is `test_business_namespaces_are_placeholders_only`, which still
requires every business Skill directory to contain only `__init__.py`. This contradicts
the later Fast Track authorization and can only be changed by Codex-00. The implementation
does not modify or suppress that test.

## Integration scope

The eight-Skill acceptance fixture is synthetic and validates each public Interface and RC
evidence shape independently. It proves the gate logic and proves a composition pass cannot
promote a failing Skill. It is not an actual verdict on other worklines, whose source commits
and RC bundles are not present on this branch.

## Pending gates

- Codex-00 baseline guard update and shared eighth-Skill registration request.
- Actual RC bundles from the seven peer Skills before per-Skill acceptance verdicts.
- V-07 relative-path allowlist/CatPaw evidence before T0-T3 Direct Verification.
- Codex-00 coverage, SBOM/license, release packaging, and rollback evidence.
- FTG-3, FTG-4, and FTG-5 decisions remain external gates.

Rollback is by reverting the eventual Codex-06 merge commit; no migration, schema change,
Library write, or external side effect requires data rollback.
