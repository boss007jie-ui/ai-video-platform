# Video Enhancement

Status: `RC_OFFLINE`; local interface `0.1.0`; contract status
`DRAFT_UNREGISTERED`. This skill is independent from Video Generation and does not
import another skill's private implementation.

The public `VideoEnhancementInterface` and six-command CLI validate and orchestrate
local video enhancement requests. Supported declarative operations are `upscale`,
`frame_interpolation`, and `denoise_restore`. The shipped adapters are deterministic
Fake and fail-closed Rejecting implementations. `RunningHubVideoEnhancementAdapter`
is a Protocol seam only: this release contains no RunningHub HTTP client, endpoint,
credential resolver, or real workflow binding.

Preflight verifies a local regular file, MP4/AVI/MOV/MKV extension and matching
container bytes, actual byte length, caller-declared byte length, SHA-256, and the
30MB upload ceiling. It then applies the selected workflow profile's duration,
resolution, FPS, output-transform, execution, and cost caps. There is deliberately
no invented platform-wide duration limit; the Fake profile owns only its test cap,
and a future real profile must be separately approved and digest-bound.

Only `OWNED` and `SYNTHETIC` media with `provider_eligible` lifecycle may pass.
`UNKNOWN`, `internal_analysis_only`, third-party references, Research Library media,
and the three specifically identified TikTok research assets are rejected before
an adapter call. Those three assets are permanently excluded by both canonical file
name and SHA-256. No excluded media is opened by this skill's acceptance flow.

Receipts record a sanitized input summary, rights state, declarative operations,
estimate-only public rate snapshot, ledger history, output digest metadata, and
`provider_network_performed: false`. They omit local absolute paths and raw Provider
job identities. Public RunningHub prices are historical snapshots, estimates only,
and explicitly not quotations.

## Commands

```text
python -m ai_video_platform.skills.video_enhancement.cli inspect-enhancement-request <file|->
python -m ai_video_platform.skills.video_enhancement.cli submit-enhancement <file|->
python -m ai_video_platform.skills.video_enhancement.cli poll-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli cancel-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli download-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli recover-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.offline_acceptance --evidence-dir <new-dir>
```

The module CLI never selects a Provider or reads a key. Inspect is offline; execution
commands without an explicitly injected Fake or Rejecting context return
`NETWORK_BLOCKED`. The independent acceptance command creates one small synthetic
fixture and a sanitized business sample, denies socket access, and demonstrates
preflight, Fake ledger completion, Rejecting fail-closed, cancel/recovery, and poll
recovery. It refuses to overwrite an evidence directory.

## Tests and rollback

```text
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_interface
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_failures
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_adapters
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_cli
py -3.14 -m unittest -v tests.skills.video_enhancement.test_video_enhancement_offline_acceptance
```

Rollback by reverting the owning FT-05-002 commit. This offline release creates no
Provider task, credential, remote asset, Library write, or registered Contract.
