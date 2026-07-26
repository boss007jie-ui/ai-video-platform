# Video Enhancement

Status: `RC_OFFLINE`; local interface `0.1.0`; contract status
`DRAFT_UNREGISTERED`. This skill is independent from Video Generation and does not
import another skill's private implementation.

The public `VideoEnhancementInterface` and owner CLI validate and orchestrate local
video enhancement requests. Supported declarative operations are `upscale`,
`frame_interpolation`, and `denoise_restore`. The shipped adapters include
deterministic Fake implementations, a fail-closed Rejecting default, and an explicit
`RunningHubVideoEnhancementAdapter`. The RunningHub path is implemented and tested
with offline transports only; no real Provider verification has been performed.

Preflight verifies a local regular file, MP4/AVI/MOV/MKV extension and matching
container bytes, actual byte length, caller-declared byte length, SHA-256, and the
30MB upload ceiling. It then applies the selected workflow profile's duration,
resolution, FPS, output-transform, execution, and cost caps. There is deliberately
no invented platform-wide duration limit; the Fake profile owns only its test cap,
and every RunningHub profile must bind its approved `workflowId`, exported workflow
JSON SHA-256, input node/field, exact `nodeInfoList`, and output origin allowlist.

Only `OWNED` and `SYNTHETIC` media with `provider_eligible` lifecycle may pass.
`UNKNOWN`, `internal_analysis_only`, third-party references, Research Library media,
and the three specifically identified TikTok research assets are rejected before
an adapter call. Those three assets are permanently excluded by both canonical file
name and SHA-256. No excluded media is opened by this skill's acceptance flow.

Offline interface receipts record a sanitized input summary, rights state,
declarative operations, estimate-only public rate snapshot, ledger history, and
output digest metadata. Explicit RunningHub execution writes a safe receipt before
the one permitted download, then finalizes output byte length and SHA-256. Receipts
omit credentials, absolute paths, and full output URLs. Public RunningHub prices are
historical snapshots, estimates only, and explicitly not quotations.

## Commands

```text
python -m ai_video_platform.skills.video_enhancement.cli inspect-enhancement-request <file|->
python -m ai_video_platform.skills.video_enhancement.cli submit-enhancement <file|->
python -m ai_video_platform.skills.video_enhancement.cli poll-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli cancel-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli download-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli recover-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli enhance <request-file> --adapter fake
python -m ai_video_platform.skills.video_enhancement.cli enhance <request-file> --adapter runninghub
python -m ai_video_platform.skills.video_enhancement.offline_acceptance --evidence-dir <new-dir>
```

`enhance` defaults to `--adapter rejecting`; the six original commands retain their
offline-only behavior. For a no-network end-to-end check, place the request JSON and
synthetic input in one temporary task workspace and select `--adapter fake`. It
writes `runninghub_enhanced.mp4` and `runninghub_enhancement_receipt.json` beside the
input, and an exact replay returns the verified local receipt without another
adapter call.

`--adapter runninghub` is the only production selection. Before using it, all of the
following must be true: `RUNNINGHUB_API_KEY` is available through the environment;
the request uses work item `FT-05-003`; `workflow_profile.workflow_binding` contains
the externally approved workflow ID and exported JSON SHA-256, the exact input
node/field and node values, and approved HTTPS output origins; the input is an
approved local MP4/AVI/MOV/MKV no larger than 30MB; and a separate real-execution
gate authorizes the call. Missing or incomplete prerequisites fail before transport.
The adapter does not use instance selection, webhook, personal queue, retention,
cancel, WSS, or the legacy status endpoint.

The independent acceptance command creates one small synthetic fixture and a
sanitized business sample, denies socket access, and demonstrates preflight, Fake
ledger completion, Rejecting fail-closed, cancel/recovery, and poll recovery. It
refuses to overwrite an evidence directory.

## Tests and rollback

```text
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_interface
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_failures
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_adapters
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_cli
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_offline_acceptance
py -3.14 -m unittest -v tests.skills.video_enhancement.test_runninghub_adapter
py -3.14 -m unittest -v tests.skills.video_enhancement.test_runninghub_cli
```

Rollback by reverting the owning FT-05-003 commit. This implementation increment
performed no Provider task, credential read, remote asset write, or registered
Contract change.
