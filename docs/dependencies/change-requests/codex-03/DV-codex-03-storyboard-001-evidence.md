# DV-codex-03-storyboard-001 Evidence

- Authorization: `FTG-0-20260720-001`
- Work item: `FT-03-001`
- Workline: `codex-03`
- Capability: V-01 story breakdown semantics, V-02 continuity semantics, and the Storyboard half of V-05
- Execution date: `2026-07-22`
- Expiry: `2026-07-29T23:59:59+08:00`
- Network: `DENIED`
- Provider smoke: `NOT_AUTHORIZED`
- Adoption authority: `NONE`

## Authorization and scope

The signed manifest and root supplement were used together. Only the fifteen allowlisted files under LSL-02 and LSL-04 were accessed. No directory was enumerated or searched. The files were hashed before content inspection, then copied into the Git-ignored `.dv-staging/DV-codex-03-storyboard-001` directory and hashed again.

This case compares public Story/Scene/Beat/Shot/Panel behavior, continuity semantics, and offline failure behavior. It does not compare or rank whole projects. Storyboard Master / Video Planning asset mapping remains a separate ownership boundary.

No Legacy module or historical test was imported or executed. No source excerpt, string value, environment value, credential value, or Provider payload is reproduced in this report.

## T0 hash gate

Result: `PASS` — source `15/15` matched, staging `15/15` matched, missing `0`, drift `0`, reparse points `0`.

| Root | Relative path | Verified SHA-256 |
|---|---|---|
| LSL-02 | `09_Tools/product_ad_workflow/story_breakdown_builder.py` | `fe7acd07041bd24540abe0c6ae60d70b9f854c04503d15a6fbcb8da850777ac2` |
| LSL-02 | `09_Tools/product_ad_workflow/storyboard_constants.py` | `32ce2a9044e5d3fac706a4e4067dc6c70ee8a29a5df1f31c18a1e59dc2f9a369` |
| LSL-02 | `09_Tools/product_ad_workflow/continuity_bible_builder.py` | `668680207cecf778e57a49aac51649e1ba9f5727ffbf97b3e30129aa1f4030ae` |
| LSL-02 | `09_Tools/product_ad_workflow/shot_panel_planner.py` | `e4168d6a2a798b73db8a9e477683417cd828605ea9478a6afaa5bafcc01f2d58` |
| LSL-02 | `07_Docs/context/storyboard_asset_continuity_permanent_rules.md` | `b116bd8cccc8bae6e397ddb0ac3dc2e97a9d7f573d0bc9bd8bb45e729289d23e` |
| LSL-02 | `tests/test_storyboard_constants.py` | `df1f4f23e1ac48fa3d450ae2d12b126dc3c4cb2464a75086b37f13bf696942e4` |
| LSL-02 | `tests/test_shot_panel_and_prompt.py` | `77ddeff421edae2e040cdcb9293f51378566dd33f416cf433c5705d1932bf30f` |
| LSL-04 | `09_Tools/product_ad_workflow/storyboard_types.py` | `5be991757bc6efb93d990da5f61006ff9305dc88bd7476eda5d8a41c7f03d9e7` |
| LSL-04 | `09_Tools/product_ad_workflow/story_breakdown.py` | `6f8b2513f9d6de02ce6dd50bd94c2fcb2aa592ec2846c28cb4b4526c02a83270` |
| LSL-04 | `09_Tools/product_ad_workflow/continuity_entities.py` | `7fb392fe8804dfa74684db8190d3cf9fbc0adb7943914892ed9320654c16d882` |
| LSL-04 | `09_Tools/product_ad_workflow/continuity_inheritance.py` | `34af1d6950a272b8ac9ed850fffac5d1159e3c3db4f4a10c51b828ebc752fd33` |
| LSL-04 | `09_Tools/product_ad_workflow/continuity_validator.py` | `9984b2d39d9d13ebf5a9ca68b68717f7626752c178d60935ca4a98a3406a6c15` |
| LSL-04 | `09_Tools/product_ad_workflow/shot_panel_planner.py` | `aa0ff24e0933f477f316794f937c9d9b534860e62db5184ec8a1c1469a42d2a5` |
| LSL-04 | `tests/test_continuity_entities.py` | `9e4cca32e731ee16880cb3f1df64b4f43296560fa4cd01562ae0c67b3dc60639` |
| LSL-04 | `tests/test_continuity_inheritance.py` | `50f5823ed5f3efdb1d54df93f3ce8133ec9332e71ed4a3dc024f87a34b23e17d` |

Read-only source-state confirmation also matched the signed records: LSL-02 is not a Git repository; LSL-04 is branch `master`, HEAD `11f2f2b91632c9e8cef2712a15e17d9e017b70f2`, with a porcelain count of two paths. No dirty path was listed, cleaned, or rolled back.

## T0 static boundary evidence

Result: `PASS_WITH_DEPENDENCY_LIMITS`.

- All fourteen Python files parsed successfully as AST; the rules document was inspected only for predefined semantic markers.
- No allowlisted file imports a network client module.
- Static write-call indicators exist in the LSL-04 breakdown and shot-panel planning modules. Those paths were not executed.
- LSL-02 candidate behavior depends on modules outside the signed allowlist, including product-fact resolution, emotional-arc design, and prompt compilation.
- LSL-04 continuity behavior depends on modules outside the signed allowlist, including continuity state, generation safety, reference manifest, and shot-asset planning.
- The dependency boundary prevents a safe historical runtime or historical test execution without a new signed manifest.

## Functional behavior comparison

| Storyboard behavior | Allowlisted Legacy static evidence | New Storyboard public-seam evidence | Assessment |
|---|---|---|---|
| Story/Scene/Beat/Shot/Panel hierarchy | Both roots define hierarchical story breakdown and panel structures | Completeness, object shape, unique IDs, panel limits, immutable snapshots, and continuity validation pass | `COVERED` |
| Raw-script story decomposition | LSL-02 exposes script-to-scene/beat/shot splitting plus emotion and shot-size detection | Current public interface accepts a caller-supplied structured plan; it does not decompose raw script | `FUNCTIONAL_GAP` |
| Automatic shot/panel planning | Both roots expose panel construction/planning shapes; LSL-02 includes panel-count/type selection indicators | Current public interface validates supplied shots/panels but does not choose panel count, type, layout, or key moments | `FUNCTIONAL_GAP` |
| Emotional progression | Legacy structures carry emotion start/end, shot emotion, arc, intensity, and audience feeling | New Storyboard rejects emotional regression and preserves audited values | `PARTIAL_COVERAGE`: validation exists; automatic detection/arc design is not exposed |
| Continuity change declaration | LSL-04 defines change declarations and continuity validation categories | New Storyboard rejects undeclared changes and accepts declared from/to/reason transitions | `COVERED` at the generic transition seam |
| Typed continuity bible | Legacy structures model typed character, product, scene, spatial, outfit, prop, location, and product-truth identity | New Storyboard carries generic per-panel continuity state and changes, without a typed continuity-bible/entity registry | `FUNCTIONAL_GAP` |
| Entity-specific continuity rules | LSL-04 static tests target unique entities, character/outfit relationships, product-truth protection, appearance/disappearance, geometry, hand assignment, and quantity/state changes | New generic continuity comparison detects changed keys but does not enforce those type-specific relationships or rule codes | `PARTIAL_COVERAGE` |
| Product and reference traceability | Legacy structures carry product identity/truth and reference-image fields; runtime dependency closure is incomplete | New Storyboard validates Foundation ProductContextBundle/ReferenceManifest provenance, product/SKU identity, pending-fact rejection, and required references | `COVERED_NEW_PLATFORM`; Legacy runtime equivalence not established |
| Prompt and negative constraints | Legacy panel structures contain prompt/negative-constraint fields; the compiler is outside the allowlist | New Storyboard validates nonempty prompts, product constraints, forbidden capability markers, and bounded input | `PARTIAL_COVERAGE`; compiler equivalence is not established |
| Version, hash, replay, and stale handling | LSL-04 structures expose content hashes; no authorized runtime evidence covers replay/stale behavior | New Storyboard proves deterministic hashes, exact replay, immutable revisions, stale rejection, tamper detection, and terminal cancellation | `COVERED_NEW_PLATFORM`; no Legacy equivalence claim |
| Stable failure and redaction semantics | LSL-04 exposes validation exception types; historical tests were not run | New Storyboard proves stable machine errors, exit code, path confinement, corruption handling, redaction, and Provider-shaped rejection | `COVERED_NEW_PLATFORM`; no Legacy equivalence claim |

### Confirmed new-platform coverage

- Stable `create-storyboard`, `revise-storyboard`, and `validate-continuity` public seams.
- Storyboard uses only the signed Foundation mapping subset: four input Contract IDs and three output Contract IDs. The global Foundation Registry remains unchanged at one Envelope plus eleven payload IDs.
- Story hierarchy, product constraints, reference provenance, emotional non-regression, generic continuity transitions, replay/version/stale handling, cancellation, redaction, path controls, and Provider-free execution are reproducibly covered.

### Functional gaps to route, not auto-adopt

1. Raw-script-to-structured-story decomposition is not present in the new public interface.
2. Automatic shot/panel count, type, layout, and key-moment planning is not present in the new public interface.
3. Typed continuity-bible/entity schemas and entity-specific relationship rules are not present; generic key/value continuity does not prove those semantics.

These are capability observations only. They do not authorize copying, wrapping, refactoring, migration, or adoption of a historical implementation.

### Explicitly excluded from the Storyboard gap verdict

The allowlisted static structures also reference continuity asset buckets, anchor assets, inherited asset plans, shot-asset-plan hashes, model selection, generation manifests, approvals, and video-execution packaging. Those concerns belong to Storyboard Master / Video Planning, Image/Panel Generation, QA, or release governance. They were not counted as Storyboard omissions and were not evaluated as adoption candidates.

## T1 and T3 — new-platform synthetic behavior

Result: T1 `PASS`; T3 `PASS_WITH_NOT_APPLICABLE`.

The new-platform owner suites ran from the signed case staging with Python bytecode disabled, temp writes forced under the case directory, and audit guards denying network, subprocess, and writes outside staging:

| Suite | Result |
|---|---|
| Storyboard Interface (T1) | `11 tests, PASS` |
| Storyboard Continuity (T1) | `4 tests, PASS` |
| Storyboard Failures/Safety (T3) | `21 tests, PASS` |
| Total | `36 tests, PASS` |

The run used deterministic synthetic Foundation envelopes and fake/local state only. No Provider adapter or network path was invoked.

T3 retry is `NOT_APPLICABLE`: Storyboard owns no Provider submission, polling, download, or retry adapter. Provider-shaped capabilities are rejected before artifact emission. This case did not invent a retry loop outside the owner boundary. Cancellation, rejecting-boundary behavior, path escape, permission/state confinement, and redaction were exercised and passed.

## T2 — historical candidate behavior

Result: `NOT_RUN_SAFETY_STOP`.

The historical tests import modules outside the fifteen-file allowlist. Executing them would require expanding the dependency closure and importing Legacy runtime modules, while the signed controls forbid staged candidate execution and the user instruction forbids running old code. T2 therefore stopped before import or execution. Historical test names and AST assertion shapes were used only as static behavioral evidence.

This negative result is part of the evidence. It prevents an executable-equivalence, verified-component-source, or adoption conclusion.

## Capability verdict

- Static comparison: `PARTIAL_BEHAVIOR_COVERAGE`.
- Legacy executable equivalence: `INSUFFICIENT_EVIDENCE`.
- New-platform clean-room behavior: `36/36 PASS` at the approved public seams; T3 retry is `NOT_APPLICABLE` because Storyboard has no retry-owning Provider boundary.
- Adoption proposal: `NONE`.
- Adoption Manifest change: `NONE`.

The new implementation covers the approved deterministic validation and lifecycle boundary, but it does not expose three behavior families visible in the static Legacy evidence: raw-script decomposition, automatic shot/panel planning, and typed/entity-specific continuity rules. Hermes/Codex-00 may route those observations as future requirements. This workline does not decide whether any historical component should be used.

## Evidence artifacts in ignored staging

- `analysis/static_inventory.json`: AST-only interfaces, dependencies, test names, semantic markers, and side-effect indicators; no source excerpts.
- `analysis/new_platform_probe.json`: guarded new-platform test counts and outcomes.
- `analysis/static_inventory.py` and `analysis/new_platform_probe.py`: case-local analysis harnesses, ignored and not committed.

## Stop-line attestation

- no Legacy write, cleanup, rollback, import, or execution;
- no directory enumeration beyond exact allowlisted path joins;
- no secret, credential file, `.env`, or environment value read or displayed;
- no network, media download, real Provider, or historical Provider execution;
- no source text reproduced in evidence;
- no cross-owner asset-mapping verdict;
- no adoption, migration, deprecation, or Foundation Registry change.
