# Product Knowledge RC Evidence Bundle

## Identity

- authorization: `FTG-0-20260720-001`
- work item: `FT-01-001`
- workline: `codex-01`
- branch: `ft/codex-01-product-knowledge`
- baseline: `3bf2c567aebda769ccac22b51b4339541eddb609`
- Skill/SemVer: `product-knowledge` / `1.0.0`
- evidence posture: `CLEAN_ROOM_ONLY`
- Provider smoke: `NOT_REQUIRED` (this Skill has no Provider seam)

## Implemented evidence

- Public service and owned CLI with machine JSON, validated `SkillExecutionEvent`, stable errors and exit codes.
- Product/SKU identity normalization, exact matching, unknown/empty clue rejection, high-confidence duplicate blocking, and multi-SKU ambiguity isolation.
- Versioned facts/assets with provenance; confirmed/effective-only context; pending/conflict/inferred/unapproved review isolation.
- Six canonical rule scopes and scope/binding/effective applicability.
- Immutable feedback intake, classification, semantic dedup links, evidence preservation, review/approval subject binding, and confirmed rule promotion.
- Private writer capability, optimistic version checks, exact idempotent replay, mismatch rejection, filesystem lock, atomic replace, audit, verified snapshot/restore, restored-out replay rejection, path containment, and tamper rejection.
- Operator rollback/recovery runbook, zero-external-dependency CycloneDX SBOM, and license inventory.

## Fresh verification

| Command | Result |
|---|---|
| `python -m unittest -v tests.skills.product_knowledge.test_product_knowledge_interface` | PASS — 7 tests, 0 failures/errors |
| `python -m unittest -v tests.skills.product_knowledge.test_product_library_adapters` | PASS — 5 tests, 0 failures/errors |
| `python -m unittest -v tests.skills.product_knowledge.test_product_knowledge_failures` | PASS — 8 tests, 0 failures/errors |
| `python -m compileall -q ...` with bytecode cache redirected to approved temporary storage | PASS |
| `python tools\run_offline_tests.py` | FAIL — 78 tests, 77 passed, 1 shared pre-FT placeholder assertion failed |

The sole full-suite failure is `test_business_namespaces_are_placeholders_only`, which forbids the required owned `SKILL.md`; request `DR-FT-01-002-phase3a-placeholder-guard.md` is routed to Codex-00. Foundation Registry exact 1+11, secret scan, network/Legacy guards, and reproducible wheel tests passed in that same run.

Performance budget evidence is the passing `test_in_memory_match_performance_budget`: 500 matches across 100 synthetic products complete below the declared 2-second budget. Concurrency evidence uses two independent filesystem adapter instances and proves one commit/one retryable stale rejection.

## Requests and dependencies

- `CR-FT-01-001-pending-fact-review-kind.md`: additive `pending_fact` review kind; no identity change.
- `CR-FT-01-002-producer-attestation.md`: shared trusted producer attestation seam.
- `DR-FT-01-001-coverage-tooling.md`: pinned offline line/branch coverage evidence.
- `DR-FT-01-002-phase3a-placeholder-guard.md`: authorize merged Skill implementation in shared architecture guard.
- Three template-conformant CatPaw/DV requests prepared; none executed. No adoption proposal or manifest change.

## Known limitations / gate status

- Numeric line/branch coverage is pending Codex-00 tooling; behavior coverage exists for public commands and high-risk branches.
- Serialized producer declarations receive Foundation Contract validation, but trusted producer attestation is a shared Core/Contract dependency and remains requested.
- Feedback consolidation implements confirmed rule promotion; additional fact/asset/known-issue/success-pattern promotion strategies remain future vertical slices.
- The existing Foundation review kind lacks exact `pending_fact`; current review-only compatibility mapping never contaminates confirmed context.
- Full offline suite cannot be green until Codex-00 updates the obsolete placeholder-only guard.
- Targeted DV is prepared but not executed; no Legacy capability is adopted.

Accordingly this packet is `REVIEW`, not `RC_OFFLINE`, `PRODUCTION_READY`, or `RELEASED`. It is safe to merge only after the integration owner evaluates the four requests and reruns the full offline gate.
