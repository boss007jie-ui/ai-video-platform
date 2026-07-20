# Storyboard Master / Video Planning

Status: `RC_OFFLINE`; version `0.1.0`; DV status `CLEAN_ROOM_ONLY`.

This Skill deterministically composes a StoryboardMaster, shot-to-asset mapping,
visual anchors, motion plan, and VideoExecutionPackage from an already-versioned
Storyboard plus approved AssetManifest-style input. It validates stale revisions,
mapping completeness, asset approval, continuity, and package integrity.

It does not generate media, call or expose a Provider adapter, read credentials,
use the network, search Legacy, write a Library, publish Foundation payloads, or
submit video work. All business artifacts are explicitly `DRAFT_UNREGISTERED`
until Codex-00 completes the Business Artifact Registry request.

## Public interface and commands

- `VideoPlanningInterface.compose_storyboard_master(request)`
- `VideoPlanningInterface.build_video_plan(request)`
- `VideoPlanningInterface.validate_video_plan(package)`
- `python -m ai_video_platform.skills.storyboard_master_video_planning.cli <compose-storyboard-master|build-video-plan|validate-video-plan> <file|->`

The CLI emits one machine-readable JSON result and exits `0` on success or `2`
on validation rejection. Hermes may call only these public surfaces and must not
interpret a draft output as a registered Contract or completed Provider action.

## Inputs, outputs, and boundaries

Inputs are JSON-compatible mappings. Revisions and source digests are locked into
each output. Same logical input produces the same canonical digest regardless of
mapping key order. Outputs are isolated snapshots; no caller object is retained.
The interface reads only supplied task data and returns in-memory planning output.

Stable errors cover invalid input, stale versions, missing/unapproved/ambiguous
assets, continuity conflict, invalid shot ordering, malformed/tampered packages,
and forbidden Provider-submission markers. Rejections happen before output and are
non-retryable until inputs change. Successful calls are naturally idempotent.

There is no fake Provider success mode because Provider work is outside Planning;
the execution package records `planning_provider_submission_performed: false`.

## Tests, release, and rollback

Run:

```text
python -m unittest -v tests.skills.storyboard_master_video_planning.test_video_planning_interface
python -m unittest -v tests.skills.storyboard_master_video_planning.test_video_planning_failures
```

Rollback is the owning commit revert/removal of this isolated Skill and tests.
There is no external state, Provider job, credential, or Library write to undo.
