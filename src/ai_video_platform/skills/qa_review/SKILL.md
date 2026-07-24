# QA / Review Skill

Version: `1.0.0`
Skill ID: `qa-review`
Execution mode: deterministic, offline, clean-room

## Responsibility

Evaluate versioned task artifacts for Contract validity, asset approval, product/SKU identity,
continuity, drift, and numeric quality criteria. Results are `pass`, `fail`, or
`needs-review`, with a structured human review package.

This Skill does not perform Reference Analysis semantic comparison, issue approvals,
write Product Library or Product/Review Context, call Providers, or access Legacy sources.

## Public commands

Invoke with `python -m ai_video_platform.skills.qa_review`:

```text
review-asset
review-storyboard
review-video-plan
review-video-result
review-artifact
review-composition
```

Every command requires `--request <utf8-json>` and `--output-dir <task-output-directory>`.
Exit codes are `0` pass, `2` fail, `3` needs-review, and `64` sanitized input/state error.

`review-artifact` evaluates one canonical storyboard-chain artifact. Its context may provide
`available_artifact_refs` for immutable upstream references resolved by the caller.
`review-composition` evaluates the complete synthetic/offline chain across all thirteen
canonical `1.0.0` artifact identities. Both commands publish QA review artifacts only.

## Input Interface

Request schema `1.0.0` requires:

- `criteria_version` and `evaluation_set_version`;
- command, task ID, and execution ID;
- versioned subject, criteria, task context, and evidence references.

Unsupported major versions fail with `QA_SCHEMA_UNSUPPORTED`. Missing fields fail with
`QA_INPUT_INVALID`. Semantic reference comparison criteria fail with
`QA_CRITERION_FORBIDDEN`.

Storyboard-chain review blocks missing ProductContextBundle, copied reference identity,
panel/product or revision mismatch, incomplete master timing/motion, unapproved execution
panels, analysis-board/contact-sheet misuse, unsupported identity/version, wrong producer,
and broken immutable provenance. Every chain failure identifies the offending artifact and
the registered owning producer in the human review package.

## Outputs

The output allowlist is exactly:

- `review-decision.json` (`ReviewDecision`);
- `feedback-events.json` (zero or more `FeedbackEvent` records);
- `skill-execution-event.json` (`SkillExecutionEvent`);
- `human-review-package.json` (versioned QA artifact);
- `result.json` (machine-readable outcome and Interface version).

The writer rejects Product Library, Research Library, Legacy, and non-allowlisted targets
before creating directories. Files are written atomically within the selected task output.

## Checks and ordering

Validation occurs before output. Checks run in stable order: Contract, subject version,
product context version, asset approval, product identity, continuity, drift, quality,
and partial failure. Any fail result dominates needs-review; needs-review dominates pass.
Stale inputs and missing evidence fail closed to human review.

## Idempotency, retry, cancellation, and recovery

The same immutable request produces the same review and feedback identities. Output files
are replaced atomically. Cancellation before evaluation returns `QA_CANCELLED` without
outputs. Recovery records `retry_of_execution_id` in the execution event.

## Stable errors

- `QA_INPUT_INVALID`
- `QA_SCHEMA_UNSUPPORTED`
- `QA_COMMAND_UNSUPPORTED`
- `QA_CRITERION_FORBIDDEN`
- `QA_OUTPUT_PATH_FORBIDDEN`
- `QA_CANCELLED`

Errors are machine-readable, non-retryable by default, and contain sanitized field paths.

## Fake/rejecting mode and external seams

QA has no Provider or network seam. The only filesystem seam is `QAOutputWriter`, which is
an allowlisted rejecting boundary for governed locations. Synthetic fixtures are the fake
input surface. The repository-wide network deny guard remains active in offline tests.

## Verification

```powershell
python -m unittest -v tests.skills.qa_review.test_qa_review_interface
python -m unittest -v tests.skills.qa_review.test_qa_review_permissions
python -m unittest -v tests.skills.qa_review.test_qa_review_evaluation
python -m unittest -v tests.skills.qa_review.test_storyboard_artifact_chain
python -m unittest discover -s tests\integration -t . -p 'test_*.py' -v
python -m unittest discover -s tests\golden -t . -p 'test_*.py' -v
```

Hermes may call only the public commands and route the resulting immutable contracts. It
does not gain additional write authority. Codex-06 owns this Skill; shared Contract/Core,
root CLI, orchestration, integration runner, dependency, and release changes route to
Codex-00.
