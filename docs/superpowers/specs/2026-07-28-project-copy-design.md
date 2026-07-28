# Project Copy Design

## Goal

Add a small offline project-copy capability that lets an AI inspect a completed
video project, ask the user which generated assets to retain, and create an
independent draft project. The complete creative content of the final script is
retained as source material. Selected character, scene, product, and storyboard
images are copied as real files rather than linked to the source project.

This capability is independent of Hermes Runner for now.

## Public Interface

The module `ai_video_platform.orchestration.project_copy` exposes two CLI
operations:

- `inspect --source <project-directory>` returns a JSON inventory.
- `copy --request <request.json>` creates the new draft project.

Inspection is side-effect free. Its output groups reusable content into:

- complete script artifacts;
- character anchors;
- scene anchors;
- product references;
- storyboard panels;
- other image references that require an explicit user choice.

Each asset candidate has a deterministic candidate ID, source-relative path,
byte size, and SHA-256 digest. Duplicate image bytes are listed once, preferring
curated deliverables over workspace/provider output copies. An execution AI can
turn this inventory into a natural-language choice for the user.

The copy request contains only:

- source project directory;
- destination project directory;
- new project ID;
- `inventory_digest` returned by inspection;
- candidate IDs explicitly selected by the user.

The complete script set is always copied. JSON scripts are converted to a draft
snapshot that keeps product content, actions, dialogue, CTA, shot order, timing,
camera instructions, character descriptions, and scene descriptions while
removing old execution identity. Markdown scripts are copied byte-for-byte.
Generated images are copied only when their candidate IDs were selected.

## Discovery Rules

The script set consists of canonical final planning material when present:

- `production_storyboard_plan.json`;
- `production_storyboard_panel_plan.json`;
- `STORYBOARD_HUMAN.md`;
- `CTA_OPTIONS.md`.

Files may appear below nested step directories. Matching is by exact file name,
not by arbitrary JSON contents. This keeps Provider requests, receipts, and
intermediate validation records out of the reusable script set.

Canonical script JSON can contain operational fields even though it is a
creative artifact. The reusable draft recursively removes only these fields:

- `task_id`, `idempotency_key`, `authorization_id`, and `approval_record`;
- `approval_status` and `approved_by`;
- `contract_id`, `contract_identity`, and `source_contract_ids`;
- `payload_digest`, `source_hashes`, and `source_provenance`;
- `artifact_id`, `producer`, and a top-level prior run `status`.

Product/SKU IDs and semantic `provider_reference_role` values remain because
they are part of the copied creative plan. The destination manifest records
both the source digest and the sanitized copy digest.

Reusable images are discovered from common image extensions. Their role is
derived from stable artifact names:

- `character-anchor-*` is a character asset;
- `scene-anchor-*` is a scene asset;
- `S<shot>-P<panel>` and `S<shot>-detail-P<panel>` are storyboard panels;
- non-anchor images in a `refs` or `input` directory are product references;
- remaining images are reported as `other_reference` and require explicit
  selection.

Symlinks and files outside the source project are never followed.

## Destination Layout

The destination must not already exist and must not be inside the source
project. Copying creates:

```text
<destination>/
  PROJECT_COPY.json
  reuse_source/
    scripts/<original relative paths>
    assets/<role>/<candidate-id>-<original name>
```

Copied source material is intentionally separated under `reuse_source`. It is
input for the next AI-guided revision, not a completed executable artifact from
the new project. Script JSON uses a `project-copy-draft-script-v1` envelope so
it cannot be mistaken for its original Contract type.

`PROJECT_COPY.json` records schema version, new project ID, source project,
creation time, draft status, copied relative paths, roles, byte sizes, source
digests, and copied digests. It contains no Provider identity or old execution
state.

## Hard Exclusions

The copy operation never carries forward:

- `.hermes` state;
- approvals or authorization records;
- Provider task IDs, idempotency keys, receipts, ledgers, locks, or temporary
  files;
- Provider output directories;
- generated videos, enhanced videos, audio, or storyboard sheet PNGs;
- QA results, failure records, audit logs, or prior run status.

The source project is read-only. The operation performs no network or Provider
calls.

## Validation And Failure Behavior

- Source must be an existing local directory.
- Destination must be new, outside the source, and not a symlink.
- Project ID follows the Runner's existing conservative identifier syntax.
- Every selected candidate ID must come from a fresh inspection of the same
  source project.
- The supplied inventory digest must match that fresh inspection, so a source
  change after the user chooses assets fails instead of silently copying a
  different revision.
- Source files are re-hashed while copying; mutation between inspection and copy
  fails and removes the incomplete destination. Sanitized JSON script output is
  hashed separately.
- Name collisions fail instead of overwriting.
- Empty script discovery fails because a script-structure copy would otherwise
  be misleading.
- Any validation or I/O failure leaves the source untouched and removes the
  incomplete destination.

## Tests

Tests exercise the public inspection and copy interfaces plus the CLI boundary:

- inspection groups and de-duplicates representative script and image assets;
- complete script files and only selected images are physically copied;
- selected image bytes and manifest digests match the source;
- script creative content is complete while old task, approval, Contract, and
  execution identity fields are absent;
- task receipts, ledgers, `.hermes`, videos, sheet PNGs, and Provider output are
  excluded;
- unknown candidate IDs, missing scripts, source mutation, existing/nested
  destinations, and symlinks fail closed;
- CLI output is machine-readable and inspection has no side effects.
