# Product Image / Panel Offline Release Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce a Provider-neutral fail-closed Adapter contract and publish a sanitized, reproducible offline CLI release receipt without selecting or calling a real Provider.

**Architecture:** `ImageProviderAdapter` is an ABC with required `provider_id` and internal `_generate` members; its inherited public `generate` always rejects. `ImagePanelService` accepts only ABC instances, while an owned AST architecture test prevents production `_generate` calls outside `service.py` and `adapters.py`. A committed evidence bundle records actual inspect/Fake/replay/Rejecting CLI processes, the ledger, runtime, static scans, authorization skeleton, release commits, and rollback.

**Tech Stack:** Python standard library `abc`, `ast`, `unittest`, existing Foundation contracts, existing Skill-local CLI and JSON codec.

## Global Constraints

- Authorization is `FTG-0-20260720-001`; Provider execution remains `NOT_AUTHORIZED`.
- Do not choose a Provider, use network access, read credentials, install a Provider SDK, or generate real media.
- Keep CLI Adapter selection to the explicit `fake` and `rejecting` values, defaulting to `rejecting`.
- Do not describe `_generate` as a security or authentication boundary.
- Only `service.py` and `adapters.py` may call `_generate` in production source.
- `pyproject.toml` stays unchanged at `requires-python = ">=3.12"`.
- The local verification runtime is Python 3.14; Python 3.12 is recorded as `NOT_RUN_ENVIRONMENT_UNAVAILABLE_USER_DIRECTED_LOCAL_3_14`.
- Evidence contains JSON, Markdown, and text only: no binary, secret, credential value, real endpoint, or real product/customer data.

---

### Task 1: Adapter ABC and service admission

**Files:**
- Modify: `tests/skills/product_image_panel_generation/test_image_panel_adapters.py`
- Modify: `tests/skills/product_image_panel_generation/test_image_panel_safety.py`
- Modify: `src/ai_video_platform/skills/product_image_panel_generation/adapters.py`
- Modify: `src/ai_video_platform/skills/product_image_panel_generation/service.py`
- Modify: `src/ai_video_platform/skills/product_image_panel_generation/__init__.py`

**Interfaces:**
- Produces: `ImageProviderAdapter.provider_id: str`, `ImageProviderAdapter.generate(...) -> ProviderAsset`, and `ImageProviderAdapter._generate(ProviderInvocation, *, cancellation: CancellationToken) -> ProviderAsset`.
- Consumes: existing `ProviderInvocation`, `ProviderAsset`, `CancellationToken`, and `ImagePanelErrorCode.PROVIDER_BYPASS_FORBIDDEN`.

- [ ] **Step 1: Write failing Adapter contract tests**

Add tests that import `ImageProviderAdapter`, assert an incomplete subclass raises `TypeError` on instantiation, assert an attempted `generate` override raises `TypeError` during subclass creation, assert Fake/Rejecting are ABC instances, assert direct `generate` returns `PROVIDER_BYPASS_FORBIDDEN`, and assert `ImagePanelService` rejects a duck-typed object.

```python
class MissingGenerate(ImageProviderAdapter):
    @property
    def provider_id(self) -> str:
        return "offline-test"

with self.assertRaises(TypeError):
    MissingGenerate()

with self.assertRaises(TypeError):
    class UnsafePublicAdapter(ImageProviderAdapter):
        def generate(self, *_args, **_kwargs):
            raise AssertionError("must not override")

        @property
        def provider_id(self) -> str:
            return "offline-test"

        def _generate(self, invocation, *, cancellation):
            raise AssertionError("not invoked")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_adapters tests.skills.product_image_panel_generation.test_image_panel_safety`

Expected: import failure for missing `ImageProviderAdapter` or contract assertions fail.

- [ ] **Step 3: Implement the minimal ABC and service check**

Add the ABC, prohibit subclass overrides of public `generate`, convert Fake/Rejecting to concrete subclasses, export it, type the service constructor, and reject non-ABC objects before assigning the Provider.

```python
class ImageProviderAdapter(ABC):
    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "generate" in cls.__dict__:
            raise TypeError("Image Provider adapters cannot override fail-closed generate()")

    @property
    @abstractmethod
    def provider_id(self) -> str:
        raise NotImplementedError

    def generate(self, *_args, **_kwargs) -> ProviderAsset:
        raise _bypass_error()

    @abstractmethod
    def _generate(self, invocation: ProviderInvocation, *, cancellation: CancellationToken) -> ProviderAsset:
        raise NotImplementedError
```

Update test-only Exploding, Leaky, and Blocking adapters to inherit one abstract test base that supplies the offline-fake `provider_id`; each retains its existing `_generate` behavior and assertions.

- [ ] **Step 4: Run Adapter and safety tests and verify GREEN**

Run the Step 2 command.

Expected: all Adapter and safety tests pass; the normal success test and exact replay test each assert `adapter.total_attempts == 1`.

- [ ] **Step 5: Commit the Adapter contract**

```powershell
git add src/ai_video_platform/skills/product_image_panel_generation tests/skills/product_image_panel_generation/test_image_panel_adapters.py tests/skills/product_image_panel_generation/test_image_panel_safety.py
git commit -m "feat(image-panel): enforce provider adapter contract"
```

### Task 2: Direct-bypass AST architecture guard

**Files:**
- Create: `tests/skills/product_image_panel_generation/test_image_panel_architecture.py`

**Interfaces:**
- Produces: `_find_direct_generate_calls(relative_path: str, source: str) -> tuple[str, ...]` used only by owned architecture tests.
- Consumes: production Python files under `src/ai_video_platform`.

- [ ] **Step 1: Write the synthetic RED test first**

Create an AST walker that is initially a stub returning no findings, then add a test expecting `rogue.py:2` for `adapter._generate(invocation, cancellation=token)`.

```python
def test_guard_rejects_non_allowlisted_direct_generate_call(self) -> None:
    source = "def bypass(adapter, invocation, token):\n    return adapter._generate(invocation, cancellation=token)\n"
    self.assertEqual(_find_direct_generate_calls("rogue.py", source), ("rogue.py:2",))
```

- [ ] **Step 2: Run the architecture module and verify RED**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_architecture`

Expected: synthetic guard test fails because the stub returns `()`.

- [ ] **Step 3: Implement the AST guard and actual-tree test**

Walk `ast.Call` nodes whose function is `ast.Attribute(attr="_generate")`. Allow results only when the relative path is exactly `ai_video_platform/skills/product_image_panel_generation/service.py` or `ai_video_platform/skills/product_image_panel_generation/adapters.py`. Scan every `*.py` under `src/ai_video_platform` and assert no violations.

- [ ] **Step 4: Run the architecture module and all owned tests**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_interface tests.skills.product_image_panel_generation.test_image_panel_adapters tests.skills.product_image_panel_generation.test_image_panel_safety tests.skills.product_image_panel_generation.test_image_panel_architecture`

Expected: all owned tests pass, including the synthetic forbidden-call proof.

- [ ] **Step 5: Commit the AST guard**

```powershell
git add tests/skills/product_image_panel_generation/test_image_panel_architecture.py
git commit -m "test(image-panel): guard internal adapter call sites"
```

### Task 3: Explicit CLI selection and sanitized evidence inputs

**Files:**
- Modify: `tests/skills/product_image_panel_generation/test_image_panel_interface.py`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/sanitized-fake-request.json`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/sanitized-rejecting-request.json`

**Interfaces:**
- Produces: two valid Skill-local input documents with distinct request and idempotency identities.
- Consumes: existing `generation_request_to_mapping`, `model_profile_to_mapping`, and clean-room test builders.

- [ ] **Step 1: Add a CLI test rejecting an unknown Adapter value**

Call `cli_main(["generate-panel", "--input", "unused.json", "--adapter", "auto"], stdout=output)` and assert exit code `2`, `IMAGE_PANEL_CONTRACT_INVALID`, and no Provider result.

- [ ] **Step 2: Verify RED or existing explicit rejection**

Run: `$env:PYTHONPATH=$null; py -3.14 -m unittest -v tests.skills.product_image_panel_generation.test_image_panel_interface.ImagePanelInterfaceTests.test_cli_rejects_unknown_adapter`

Expected: RED if the test is absent; after adding it, the existing parser should make it pass without production CLI changes. This records existing behavior rather than adding a dynamic selector.

- [ ] **Step 3: Generate and inspect sanitized JSON inputs**

Use a one-off offline Python process with `tests.skills.product_image_panel_generation._support` and the existing codecs to build a Fake document for `product-sanitized-wallpanel-001` and a Rejecting document with a distinct request ID/key and profile digest. Mechanically write only the two JSON artifacts, then scan them for secret patterns, `http://`, `https://`, and non-memory URIs.

- [ ] **Step 4: Commit inputs and CLI selection test**

```powershell
git add tests/skills/product_image_panel_generation/test_image_panel_interface.py src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/sanitized-*-request.json
git commit -m "test(image-panel): add sanitized offline CLI fixtures"
```

### Task 4: Run the real CLI receipt sequence

**Files:**
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/01-inspect.stdout.json`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/02-fake.stdout.json`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/03-replay.stdout.json`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/04-rejecting.stdout.json`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/ledger-receipt.json`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/receipt-manifest.json`

**Interfaces:**
- Produces: sanitized immutable evidence for four CLI stages plus invocation-count and exit-code assertions.
- Consumes: Task 3 input documents and current module CLI.

- [ ] **Step 1: Run inspect, Fake, replay, and Rejecting as separate CLI processes**

Use `set PYTHONPATH=src&& py -3.14 -m ai_video_platform.skills.product_image_panel_generation.cli ...` for each real module CLI invocation. Capture exactly one JSON stdout object per file and record exit codes `0`, `0`, `0`, and `3`.

- [ ] **Step 2: Preserve the ledger receipt without leaving an active ledger**

Rename the generated `.image-panel-generation-ledger.json` to `ledger-receipt.json`; assert no `.lock` file remains. The ledger must contain both idempotency records and no credential/provider payload.

- [ ] **Step 3: Build and validate receipt-manifest.json**

Record the four commands, exit codes, output SHA-256 values, `adapter_invocation_count_after_fake: 1`, `adapter_invocation_count_after_replay: 1`, `replayed: true`, and `provider_smoke: NOT_AUTHORIZED`. Parse all JSON artifacts again before commit.

- [ ] **Step 4: Commit the receipt**

```powershell
git add src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/*.json
git commit -m "docs(image-panel): record offline CLI receipt"
```

### Task 5: Provider authorization skeleton and operational record

**Files:**
- Modify: `src/ai_video_platform/skills/product_image_panel_generation/SKILL.md`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/FTG-P-003-PROVIDER-AUTHORIZATION-SKELETON.md`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/python-runtime.txt`
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/static-scan.txt`

**Interfaces:**
- Produces: the unsigned Provider-neutral gate card and offline operating instructions.
- Consumes: exact Adapter/AST/input/receipt commits from Tasks 1–4.

- [ ] **Step 1: Write the unsigned FTG-P-003 skeleton**

Include authorization, scope, stop conditions, endpoint, billing, quota, input constraints, output constraints, credential reference type, bounded smoke, redaction, budget, rollback, and evidence fields. Provider-dependent fields use the exact sentinel `TBD_BY_HERMES_AFTER_USER_DECISION`; credential values are explicitly forbidden.

- [ ] **Step 2: Update Skill operations and runtime statement**

Document `INTERNAL_PRODUCTION_READY_OFFLINE` separately from real path `RC_PROVIDER_PENDING`, Python 3.14 verification, absent 3.12 runtime, explicit Adapter allowlist, and the AST guard. Do not claim full Production Ready.

- [ ] **Step 3: Capture runtime and static scans**

Record `py -3.14 --version`, the unavailable 3.12 result, and scan results proving no secret patterns, real endpoints, Provider SDK imports, or binary files in the evidence bundle.

- [ ] **Step 4: Commit Provider preparation and operations**

```powershell
git add src/ai_video_platform/skills/product_image_panel_generation/SKILL.md src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722
git commit -m "docs(image-panel): prepare provider-neutral offline release"
```

### Task 6: Final verification and release record

**Files:**
- Create: `src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/OFFLINE_RELEASE_RECORD.md`

**Interfaces:**
- Produces: exact release commit list, test results, rollback commands, evidence inventory, and status split.
- Consumes: all previous task commits.

- [ ] **Step 1: Run all owned tests on Python 3.14 with PYTHONPATH cleared**

Run each owned module, including `test_image_panel_architecture`, with `$env:PYTHONPATH=$null; py -3.14 -m unittest -v ...` and record exact counts.

- [ ] **Step 2: Run the full offline suite**

Run: `$env:PYTHONPATH=$null; py -3.14 tools\run_offline_tests.py`

Expected: exit code `0`, no failures. Record the exact test count.

- [ ] **Step 3: Re-run evidence and ownership scans**

Run `git diff --check`, parse every evidence JSON file, scan source for disallowed `_generate` calls, and confirm changed paths stay under the Codex-04 owner boundaries.

- [ ] **Step 4: Write OFFLINE_RELEASE_RECORD.md**

Record the exact capability and evidence commit SHAs, exact commands/results, Python runtime, 3.12 non-run disposition, receipt hashes, no-network/no-secret attestations, status `INTERNAL_PRODUCTION_READY_OFFLINE`, real path `RC_PROVIDER_PENDING`, and reverse-order `git revert` commands.

- [ ] **Step 5: Commit the release record**

```powershell
git add src/ai_video_platform/skills/product_image_panel_generation/evidence/offline-release-20260722/OFFLINE_RELEASE_RECORD.md
git commit -m "docs(image-panel): publish offline release record"
```

- [ ] **Step 6: Verify final clean state**

Run `git status --short --branch`, `git rev-parse HEAD`, and inspect every first-parent commit created by this plan. The worktree must be clean before emitting `hermes_status`.
