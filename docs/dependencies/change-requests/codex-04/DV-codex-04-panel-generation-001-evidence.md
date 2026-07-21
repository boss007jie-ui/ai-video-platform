# DV-codex-04-panel-generation-001 Evidence

Authorization: `FTG-0-20260720-001`
Work item: `FT-04-001`
Workline: `codex-04`
Capability: V-04 Product Image / Panel generator and prompt compile boundary
Execution date: `2026-07-20`
Network: `DENIED`
Provider smoke: `NOT_AUTHORIZED`

## Scope and controls

The case used only the six relative paths frozen in `DV-codex-04-panel-generation-001-manifest.json`. LSL-02 and LSL-04 were read-only. Copies were placed under the Git-ignored `.dv-staging/DV-codex-04-panel-generation-001` directory after source hash verification. No historical module was imported, no historical test was executed, no Provider was called, and no source text or credential value was printed into this evidence.

LSL-06 was not added to this case because the available static Audit evidence did not provide an equally complete, per-file current hash/path freeze for the Runtime generator family. This case does not infer that Sandbox and Runtime behavior are equal.

## Source state confirmation

| Root | Current read-only observation | Audit comparison |
|---|---|---|
| LSL-02 production | Not a Git repository at the authorized root | Audit lineage label retained as historical evidence only |
| LSL-04 sandbox | branch `master`; HEAD `11f2f2b91632c9e8cef2712a15e17d9e017b70f2`; 9 porcelain paths | differs from Audit `ee2c503` / 87 dirty record; source was not cleaned or rolled back |

All six current source SHA-256 values exactly matched the manifest's Audit hashes:

| Root | Relative path | SHA-256 |
|---|---|---|
| LSL-02 | `09_Tools/product_ad_workflow/panel_image_generator.py` | `3f3787c01489a3f503e33fd79f066408b6c69d5e2798dd1d72c010240b991949` |
| LSL-02 | `09_Tools/product_ad_workflow/panel_prompt_compiler.py` | `6e8b9c6e5cdf19e7c4b50e83f23adf7394d70c38b88a9ad4834e94d68db1afb2` |
| LSL-02 | `tests/test_shot_panel_and_prompt.py` | `77ddeff421edae2e040cdcb9293f51378566dd33f416cf433c5705d1932bf30f` |
| LSL-04 | `09_Tools/product_ad_workflow/refined_panel_generator.py` | `4b905df9f83b96b499a4e35e2624ef435c31340fb37a4f463fc90675583342df` |
| LSL-04 | `09_Tools/product_ad_workflow/panel_prompt_compiler.py` | `e0863abbd6c3b6ec9370bfc37b7d768f6ebc9ac05fccc4cc9208e3ae2ce3686b` |
| LSL-04 | `tests/test_prompt_compiler_truth.py` | `191cbe737cb45eb8b9a54c39da8ca4ab86dbcbbb06e03a3ce1097e3fd515ffa8` |

Staging hashes matched the same values after copy. None of the six files was a symlink or junction.

## T0 — static boundary review

Result: `PASS_WITH_RISKS`

- all six files parsed as Python AST and passed `compile()` without execution;
- the bounded secret-pattern probe reported zero rule IDs for all six files;
- neither candidate generator exposed the approved three-command Skill CLI;
- LSL-02 exposes `generate_panel_images` and `save_panel_generation_result`;
- LSL-04 exposes `generate_refined_panels` and `_render_refined_review`;
- both generator families contain task-file `write_text` indicators;
- LSL-02 generator imports internal adapter routing, mock image adapters, storyboard constants, QA checker, and its prompt compiler;
- LSL-04 generator imports model selection, panel QA, storyboard adapters/types, and its prompt compiler;
- LSL-02 prompt compiler imports product knowledge loader/truth resolver, asset-manifest reader, and storyboard constants;
- LSL-04 prompt compiler imports generation safety, product truth, continuity, shot asset planning, and storyboard types;
- the staged tests import additional modules outside the case allowlist.

The static indicators are evidence of dependency and side-effect risk. They do not prove a real network call occurred and were not used to execute or rank a source as canonical.

## T1 — Contract and public-shape mapping

Result: `PARTIAL_MAPPING_ONLY`

| Target requirement | LSL-02 static shape | LSL-04 static shape | Mapping result |
|---|---|---|---|
| independent stable public commands | function entrypoints only | function entrypoint only | no direct CLI fit |
| Foundation Task/Product/Approval inputs | no approved envelope surface found in allowlisted imports | no approved envelope surface found in allowlisted imports | adapter/refactor layer would be required |
| deterministic prompt compile | compiler functions exist | compiler functions and truth validation exist | behavior not compared without T2 dependency closure |
| task-owned AssetManifest output | no approved Foundation output demonstrated | no approved Foundation output demonstrated | unresolved |
| budget/idempotency/retry/cancel/concurrency | not demonstrated by allowlisted public shape | not demonstrated by allowlisted public shape | unresolved |
| Provider bypass protection | internal adapter routing present | storyboard adapters present | incompatible with direct adoption absent a verified seam |
| Product Library write prohibition | compiler couples product loader/truth modules | compiler couples product truth modules | read/write semantics require isolation before any reuse |

No alias or new Foundation Contract ID was introduced. The mapping remains against the fixed one-Envelope plus eleven-payload registry.

## T2 — candidate unit behavior

Result: `NOT_RUN_SAFETY_STOP`

The allowlisted historical tests cannot be imported without reading and staging additional internal modules. Both generator families also import internal Adapter/QA/Storyboard/Product modules, and the generators contain file-write paths. Expanding the dependency closure would violate this case's relative-path allowlist; importing the generators could cross the historical Provider boundary. Under the manifest's fail-closed controls, T2 stopped before import or execution.

This is a recorded negative result, not a skipped successful test. No historical test count is claimed.

## T3 — new-platform fake/rejecting behavior

Result: `PASS`

Fresh commands and results:

```text
python -m unittest tests.skills.product_image_panel_generation.test_image_panel_interface
Ran 21 tests in 0.134s — OK

python -m unittest tests.skills.product_image_panel_generation.test_image_panel_adapters
Ran 11 tests in 0.018s — OK

python -m unittest tests.skills.product_image_panel_generation.test_image_panel_safety
Ran 18 tests in 0.083s — OK
```

The 50 tests cover approved contract-bound preflight, deterministic prompt compile, fake/rejecting outcomes, direct-Adapter bypass, complete model-profile digest binding, cross-contract correlation, task/product asset ownership, request hash, product identity, approved assets/reference rights, budget, dimensions/profile, ApprovalRecord, stale input, retries with real default backoff, enforced watchdog timeout, cancellation, partial failure, in-process and durable CLI idempotent replay/conflict, concurrency, Provider and unexpected-error sanitization, Foundation output validation, and no Provider SDK/cross-Skill private import.

## Capability verdict

Verdict: `INSUFFICIENT_EVIDENCE`
Execution strategy: `CLEAN_ROOM_ONLY`
Adoption proposal: `NONE`

The static evidence is sufficient to reject automatic wrap/adoption in this case, but T2 was not authorized to expand into the required dependency closure and no behavior-equivalence run occurred. Therefore this case does not claim `VERIFIED_CANDIDATE`, `VERIFIED_COMPONENT_SOURCE`, `EQUIVALENT_BEHAVIOR`, or `REIMPLEMENT_REQUIRED` for either source family.

Codex-04 continues the independently tested clean-room implementation. Any future Wrap/Refactor proposal requires a new narrow case with a complete dependency allowlist, frozen current source state, offline import harness, license/provenance evidence, and explicit Adoption Gate approval.

## Stop-line attestation

- no Legacy write or cleanup;
- no secret/credential value read or displayed;
- no network, download, image Provider, or historical Provider code execution;
- no Adoption Manifest change;
- no canonical/adopt/migrate decision derived from CatPaw/Audit recommendations;
- staging contents remain ignored and are not part of the work-item commit.
