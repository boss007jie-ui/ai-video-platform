# Revision D Evidence

## Reconstruction Status

On 2026-07-23 the original Revision D completion report was found to have no supporting repository evidence. The claimed branch, commits, and Revision D functions were absent. This implementation is therefore a zero-start reconstruction from integration baseline `047a2c2`, under dispatch v2. The v1 launch-base starting point was superseded by v2 and was not used.

The implementation was performed on branch `ft/codex-05-pipeline` in its dedicated worktree. No Provider, network, credential, or legacy project access is part of this implementation.

## Design Decisions

### Viral script data

`ViralScript` is a frozen data object with `script_id`, `content`, and optional `submitted_context`. Identity and content remain blockers. Missing, empty, or malformed submitted context is represented as a warning so downstream product-fact repair can continue without silently treating the context as confirmed knowledge.

### Product data boundary

`ProductFacts` is the product-only projection used by the image-panel preflight gateway. It contains product identity, SKU identity, confirmed facts, approved asset IDs, visual constraints, packaging, dimensions, and category IDs. `ChannelProfile` contains channel expression parameters. `repair_story_context()` belongs to `ProductFacts`; `derive_product_mode()` belongs to `ChannelProfile` and consumes `ProductFacts`.

`to_product_facts()` accepts a mapping or a validated Foundation payload object exposing its mapping `payload`, and copies only the product-domain allowlist. It intentionally does not retain the Foundation DTO, execution metadata, provider fields, or model fields. Nested mappings and sequences are frozen at construction.

### Continuity review seam

The continuity-review package is split into `references`, `assembly`, `consume`, and immutable `models`. Reference IDs are resolved against a caller-provided local index and returned in requested order. Only PNG and JPEG headers are parsed because the seam is offline and must reject unknown media rather than guess.

The loader rejects a missing path, unreadable path, non-image file, image larger than `IMAGE_MAX_BYTES = 3 * 1024 * 1024`, or image edge larger than `IMAGE_MAX_EDGE = 1792`. The error names the failed reference and the violated limit. Assembly records validated reference metadata; consume exposes only immutable paths and continuity fields.

`narrative_mode`, `lead_persona_ids`, and `scene_anchor_ids` are explicit fields on both assembly and consumption records. The consume boundary copies these values without reinterpretation, preserving tuple order.

## Verification Evidence

The baseline was verified before implementation: clean-room smoke was `6 passed`, and the offline suite was `302 tests OK, skipped=3` at the integration baseline. Revision D-specific checks then passed as follows:

- Product image owner tests: `50 passed, 2 subtests passed`.
- Contract gates: `5 tests OK`.
- Architecture gates: `4 tests OK`.
- Direct product-data probe: `product-data-probe OK`.
- Direct continuity positive probe: `continuity-probe OK`.
- Direct continuity rejection probe: `continuity-rejection-probe OK`.

The final full-suite and diff/status results are recorded in the task handoff after execution, using Python 3.14 with `PYTHONPATH` cleared and `PYTHONPATH=src` supplied explicitly where needed.

## Scope Record

Only the Revision D dispatch paths were changed: the viral-script interface, continuity-review core package, product image-panel package, and the four newly added gate tests. Existing architecture and contract tests were not edited. Research Library, KIE adapter, CLI, maintenance, other skills, and other worktrees were left untouched.
