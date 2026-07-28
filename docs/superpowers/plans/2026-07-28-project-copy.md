# Project Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline two-step project copy tool that inventories reusable content, preserves the complete creative script, and physically copies only user-selected generated images into an independent draft project.

**Architecture:** A single focused orchestration module owns discovery, immutable inventory generation, draft-script sanitization, physical copying, cleanup, and a small JSON CLI. It does not call Hermes Runner, Contracts, Skills, Providers, or the network. Public behavior is tested through `inspect_project`, `copy_project`, and `main`.

**Tech Stack:** Python 3.14 standard library (`argparse`, `datetime`, `hashlib`, `json`, `pathlib`, `re`, `shutil`), `unittest`, `pytest`.

## Global Constraints

- No Hermes Runner integration in this change.
- No Contract or Skill changes.
- No network, Provider, credential, approval, or paid execution paths.
- Source projects are read-only; selected images are physically copied.
- Preserve all creative script content, including product details, actions, dialogue, CTA, shot order, timing, camera, character, and scene descriptions.
- Strip old task, approval, Contract, artifact, producer, provenance, and run identity from copied JSON scripts.
- Never copy `.hermes`, receipts, ledgers, locks, Provider output, videos, audio, storyboard sheets, QA/failure/audit material, or prior run status.
- Tests use only temporary directories and synthetic bytes.

---

## File Structure

- Create `src/ai_video_platform/orchestration/project_copy.py`: public inspection/copy functions, validation, discovery, sanitization, atomic cleanup, and CLI.
- Create `tests/orchestration/test_project_copy.py`: public API and CLI behavior.
- Modify `docs/superpowers/specs/2026-07-28-project-copy-design.md`: include the inspection digest required by copy requests.

### Task 1: Side-Effect-Free Project Inventory

**Files:**
- Create: `src/ai_video_platform/orchestration/project_copy.py`
- Create: `tests/orchestration/test_project_copy.py`

**Interfaces:**
- Produces: `ProjectCopyError(ValueError)`.
- Produces: `inspect_project(source: Path | str) -> dict[str, object]`.
- Inventory keys: `schema_version`, `source_project`, `scripts`, `assets`, `inventory_digest`.
- Asset groups: `character`, `scene`, `product`, `storyboard_panel`, `other_reference`.

- [ ] **Step 1: Write the failing inventory test**

Create a temporary source project containing both canonical script files,
duplicate character/scene images in `deliverables` and `refs`, a product image,
a storyboard panel, a sheet PNG, Provider output, a receipt, and a video. Assert
that `inspect_project` finds both scripts, groups the four reusable image roles,
de-duplicates image bytes, excludes the sheet/output/video/evidence files, emits
`sha256:<64 lowercase hex>` digests, and does not change the source tree.

```python
inventory = inspect_project(source)
self.assertEqual([item["relative_path"] for item in inventory["scripts"]], [
    "storyboard/production_storyboard_plan/production_storyboard_panel_plan.json",
    "storyboard/production_storyboard_plan/production_storyboard_plan.json",
])
self.assertEqual(len(inventory["assets"]["character"]), 1)
self.assertRegex(inventory["inventory_digest"], r"^sha256:[0-9a-f]{64}$")
self.assertEqual(before, _tree_snapshot(source))
```

- [ ] **Step 2: Run the inventory test and verify RED**

Run:

```powershell
$env:PYTHONPATH='src'; py -3.14 -m pytest tests/orchestration/test_project_copy.py::ProjectCopyTests::test_inspect_groups_deduplicates_and_excludes_execution_files -q
```

Expected: collection/import failure because `project_copy` does not exist.

- [ ] **Step 3: Implement deterministic inspection**

Add constants for exact script names, image suffixes, excluded directory/name
markers, role order, and project ID syntax. Implement canonical JSON and SHA-256
helpers, safe source validation, non-symlink traversal, exact script discovery,
image role classification, digest-based de-duplication with priority
`deliverables` then `refs` then `input` then other paths, stable sorting, and an
inventory digest calculated over the inventory before the digest field is
added.

Candidate IDs use the full content digest:

```python
candidate_id = f"asset:{role}:{sha256_hex}"
```

- [ ] **Step 4: Run the inventory test and verify GREEN**

Run the focused command from Step 2. Expected: `1 passed`.

- [ ] **Step 5: Commit the inventory slice**

```powershell
git add -- src/ai_video_platform/orchestration/project_copy.py tests/orchestration/test_project_copy.py
git commit -m "feat(project-copy): inspect reusable project content"
```

### Task 2: Safe Draft Copy With Full Creative Script

**Files:**
- Modify: `src/ai_video_platform/orchestration/project_copy.py`
- Modify: `tests/orchestration/test_project_copy.py`

**Interfaces:**
- Consumes: inventory from `inspect_project`.
- Produces: `copy_project(request: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]`.
- Request exact keys: `source_project`, `destination_project`, `project_id`, `inventory_digest`, `selected_candidate_ids`.
- Destination manifest: `PROJECT_COPY.json` with `schema_version`, `project_id`, `source_project`, `created_at`, `status`, `inventory_digest`, `scripts`, and `assets`.

- [ ] **Step 1: Write the failing successful-copy test**

Inspect the fixture, select only one character and one scene candidate, call
`copy_project` with a fixed UTC timestamp, and assert:

```python
result = copy_project(request, now=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc))
self.assertEqual(result["status"], "draft")
self.assertEqual(result["created_at"], "2026-07-28T08:00:00Z")
self.assertEqual({item["role"] for item in result["assets"]}, {"character", "scene"})
```

Read copied JSON script envelopes and assert all creative values remain, while
`task_id`, `approval_status`, `approved_by`, Contract/artifact/provenance fields,
and top-level prior status are absent. Assert selected image bytes match source,
unselected product/panel images are absent, and source files are unchanged.

- [ ] **Step 2: Run the successful-copy test and verify RED**

Run:

```powershell
$env:PYTHONPATH='src'; py -3.14 -m pytest tests/orchestration/test_project_copy.py::ProjectCopyTests::test_copy_preserves_full_creative_script_and_only_selected_assets -q
```

Expected: failure because `copy_project` is missing.

- [ ] **Step 3: Implement script sanitization and physical copy**

Implement recursive sanitization with a fixed operational-key denylist and a
top-level `status` removal. Wrap each JSON script as:

```python
{
    "schema_version": "1.0.0",
    "document_type": "project-copy-draft-script-v1",
    "source_relative_path": relative_path,
    "content": sanitized_script,
}
```

Validate exact request keys, project ID, fresh inventory digest, selected IDs,
new destination, and destination/source separation. Create the destination,
write script envelopes using canonical UTF-8 JSON, copy selected image bytes,
verify source and destination digests, write `PROJECT_COPY.json` last, and remove
the incomplete destination on any exception.

- [ ] **Step 4: Run the successful-copy test and verify GREEN**

Run the focused command from Step 2. Expected: `1 passed`.

- [ ] **Step 5: Add failure-path tests one vertical slice at a time**

Add public-interface tests asserting `ProjectCopyError` for:

- empty script discovery;
- unknown selected candidate ID;
- stale `inventory_digest` after a source file mutation;
- existing destination;
- destination nested inside source;
- source or candidate symlink.

For cleanup, provide a canonical script file with malformed JSON. Inspection
can inventory its bytes, but copy fails while creating the draft envelope;
assert the incomplete destination no longer exists.

- [ ] **Step 6: Run all project-copy tests**

```powershell
$env:PYTHONPATH='src'; py -3.14 -m pytest tests/orchestration/test_project_copy.py -q
```

Expected: all project-copy tests pass.

- [ ] **Step 7: Commit the copy slice**

```powershell
git add -- src/ai_video_platform/orchestration/project_copy.py tests/orchestration/test_project_copy.py
git commit -m "feat(project-copy): create selective draft copies"
```

### Task 3: Machine-Readable CLI And Final Verification

**Files:**
- Modify: `src/ai_video_platform/orchestration/project_copy.py`
- Modify: `tests/orchestration/test_project_copy.py`
- Modify: `docs/superpowers/specs/2026-07-28-project-copy-design.md`

**Interfaces:**
- Consumes: `inspect_project` and `copy_project`.
- Produces: `main(argv: Sequence[str] | None = None) -> int`.
- Invocation: `py -3.14 -m ai_video_platform.orchestration.project_copy inspect --source <path>`.
- Invocation: `py -3.14 -m ai_video_platform.orchestration.project_copy copy --request <json-or-dash>`.

- [ ] **Step 1: Write failing CLI tests**

Assert inspect returns exit `0` with `{"ok": true, "result": ...}` and copy
accepts a UTF-8 request file. Assert invalid JSON and invalid requests return
exit `2` with `{"ok": false, "error": <stable non-sensitive message>}`.

- [ ] **Step 2: Run CLI tests and verify RED**

```powershell
$env:PYTHONPATH='src'; py -3.14 -m pytest tests/orchestration/test_project_copy.py -k cli -q
```

Expected: failures because `main` is missing.

- [ ] **Step 3: Implement the CLI**

Use `argparse` subcommands and canonical JSON output. Read `-` from stdin,
otherwise read the request path as UTF-8. Catch only expected validation,
filesystem, Unicode, and JSON errors and return stable error text without local
tracebacks or file contents.

- [ ] **Step 4: Run project-copy and orchestration tests**

```powershell
$env:PYTHONPATH='src'; py -3.14 -m pytest tests/orchestration/test_project_copy.py tests/orchestration/test_project_runner.py -q
```

Expected: all tests pass and Runner behavior is unchanged.

- [ ] **Step 5: Exercise inspect against an existing completed project offline**

```powershell
$env:PYTHONPATH='src'; py -3.14 -m ai_video_platform.orchestration.project_copy inspect --source run/20260727-ceiling-tile-black-stickup
```

Expected: JSON inventory with script, character, scene, product, and panel
groups; no files are created or modified in the source.

- [ ] **Step 6: Run repository checks**

```powershell
$env:PYTHONPATH='src'; py -3.14 -m pytest tests/orchestration/ -q
git diff --check
```

Expected: all orchestration tests pass and `git diff --check` has no errors.

- [ ] **Step 7: Commit CLI and design correction**

```powershell
git add -- src/ai_video_platform/orchestration/project_copy.py tests/orchestration/test_project_copy.py docs/superpowers/specs/2026-07-28-project-copy-design.md docs/superpowers/plans/2026-07-28-project-copy.md
git commit -m "feat(project-copy): expose offline copy CLI"
```
