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

It performs canonical preflight, one submission, four-second polling up to the
approved deadline (never more than 600 seconds), success-only download, MP4
content/digest validation, and exclusive evidence persistence. The output
directory must be a child of the request file's task workspace. It writes
`seedance_nz_video.mp4` and `seedance_nz_video_receipt.json`; existing or partial
evidence is never overwritten. An exact persisted `idempotency_key` plus
`request_hash` replay returns the verified receipt without constructing an
adapter or making another Provider call. Changed or tampered evidence fails
closed.

The command reads its credential only through `SEEDANCE_NZ_API_KEY`. No other
command implicitly selects Seedance.nz, and `run` remains preflight-only. A
successful receipt is marked `CONTROLLED_FIRST_RUN_REQUIRED`; it is not a
Production Ready claim. Cancellation remains unsupported and late media is not
chased after the deadline.

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
