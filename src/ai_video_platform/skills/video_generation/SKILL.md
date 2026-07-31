# Video Generation

Status: `RC_PROVIDER_PENDING`; canonical planning input version `1.0.0`;
contract status `IDENTITY_REGISTERED_SCHEMA_PENDING`; DV status `CLEAN_ROOM_ONLY`.

Video Generation accepts only a canonical `VideoExecutionPackage` containing the
independent `VideoGenerationStoryboardMaster`, `ShotMotionPlan`,
`FirstFrameMapping`, and `ReferenceRoleMapping` artifacts. Preflight verifies all
artifact identities, digests, planning revisions, shot/panel order, approved asset
bindings, clean first frame, and reference roles before approval, budget, binding,
adapter, or ledger work.

The public preflight target is:

```text
python -m ai_video_platform.skills.video_generation.cli run <file|->
```

`inspect-video-request` remains an equivalent inspection command for existing
hosts. Execution commands are `submit-video`, `poll-video`, `cancel-video`,
`download-video`, and `recover-video`; they require an explicitly injected adapter
and ledger. The module CLI never selects a real adapter and therefore fails closed.

The single explicit owner command that may select the Seedance.nz production
adapter is:

```text
python -m ai_video_platform.skills.video_generation.cli execute-seedance-nz request.json --output-dir <task-workspace-output>
```

An `ApprovalRecord` inside `request.json` is provenance for preflight; it is not
live permission to spend money. Immediately before the first real Provider
submission, this command opens a native confirmation dialog showing the project,
package, model, duration, and resolution. The user must click **Yes** for that
specific execution. **No** is the default button. Declining, closing the dialog,
or running where the dialog cannot be shown fails closed before the production
adapter is constructed. Agents must never invent `user-chat-approval-*` records
or treat approval of panels, storyboards, analysis, or project continuation as
approval to generate video.

After live confirmation, the CLI computes a stable execution fingerprint from
the Provider/model, prompt, settings, approved asset digests, and reference identities.
Approval IDs, caller-provided idempotency keys, output directories, and temporary
URL query signatures cannot change that identity. A project-wide registry under
`run/.seedance_nz_submissions/` atomically reserves the fingerprint, so changing
`v1` to `v2`, using a new approval ID, or selecting another output directory does
not resubmit an equivalent paid task. Existing reserved, submitted, or downloaded
identities fail closed; use the recorded task/receipt instead of trying another
key.

It then performs canonical preflight, one submission, four-second polling up to the
approved deadline (never more than 600 seconds), success-only download, MP4
content/digest validation, and exclusive evidence persistence. The output
directory must be a child of the request file's task workspace. It writes
`seedance_nz_video.mp4` and `seedance_nz_video_receipt.json`; existing or partial
evidence is never overwritten. As soon as submission returns, the task ID is
written both to the output pending receipt and the project-wide registry before
polling. An exact persisted `idempotency_key` plus
`request_hash` replay returns the verified receipt without constructing an
adapter or making another Provider call. Changed or tampered evidence fails
closed.

The command reads its credential only through `SEEDANCE_NZ_API_KEY`. No other
command implicitly selects Seedance.nz, and `run` remains preflight-only. A
successful receipt is marked `CONTROLLED_FIRST_RUN_REQUIRED`; it is not a
Production Ready claim. Cancellation remains unsupported and late media is not
chased after the deadline.

For `seedance-2.0-fast-multi`, build image references in this canonical order:
approved individual production Panels first in `shot_order`/`panel_order`, clean
product references next, and the storyboard master Sheet last. Mark internal
`metadata.content` items with `reference_role=production_panel`,
`product_reference`, or `storyboard_structure_reference`; the adapter performs a
stable role sort and removes that internal field from the Provider payload. Build
the prompt's concrete `@Image N` references from this canonical order. The Sheet
is a structure reference only, never a first frame, and its borders, labels,
captions, and arrows must be forbidden in generated video.

When the canonical Master timeline is over 15 seconds, the complete Master Sheet
is review-only and must not be sent to Seedance. Execute the fewest consecutive
segments published in `storyboard_master_sheet_manifest.json` as separate tasks.
Each request must declare `output.metadata.execution_segment` with the exact
`segment_id`, absolute `start_ms`/`end_ms`, `duration_ms`, ordered `shot_ids`,
ordered `panel_ids`, and the segment Sheet page digests in `sheet_sha256s`. Its
content must contain exactly the current segment's ordered production Panels and
every declared Sheet page. Each Sheet page is a `storyboard_structure_reference` marked
`storyboard_scope=execution_segment` with the same segment ID and matching digest.
Product references may remain between those roles under the adapter's canonical
sort. A complete Master Sheet, missing segment
metadata, non-consecutive Shots, a cross-segment Panel, or a duration mismatch
fails before confirmation or transport.

Each segment uses its own `execute-seedance-nz` invocation and live confirmation;
Agents must not batch-confirm or automatically submit the next segment. The
platform does not currently own a final video-stitching Skill, so separate segment
downloads must not be reported as one assembled long-form deliverable.

Reference analysis boards, shot evidence boards, replication boards, and contact
sheets cannot be first frames or Provider inputs. Unapproved panels, mismatched
revisions, order divergence, legacy `0.1.0` packages, and the obsolete
`StoryboardMaster` identity are rejected before adapter or ledger calls. The Skill
does not privately import Video Planning.

Fake, Rejecting, and NetworkBlocked adapters remain available for deterministic
offline tests. Existing KIE adapter/download code is unchanged in authority: this
delta grants no network, credential, Provider, or smoke permission. Real execution
remains fail-closed and `RC_PROVIDER_PENDING`. Downloaded media still produces the
existing draft `AssetManifestRequest`; no Product Library write occurs.

The five planning identities are registered, but their shared schemas/validators
remain a Codex-00 publication dependency. Do not claim formal production-ready
`ContractEnvelope` exchange until that gate closes.

## Tests and rollback

```text
py -3.14 -m unittest -v tests.skills.video_generation.test_video_generation_interface
py -3.14 -m unittest -v tests.skills.video_generation.test_video_generation_adapters
py -3.14 -m unittest -v tests.skills.video_generation.test_video_generation_safety
py -3.14 -m unittest -v tests.skills.video_generation.test_kie_adapter
py -3.14 -m unittest -v tests.skills.video_generation.test_video_generation_offline_acceptance
```

Rollback by reverting the owning commit. This offline delta creates no Provider
job, remote asset, credential, Library write, or formal schema publication.
