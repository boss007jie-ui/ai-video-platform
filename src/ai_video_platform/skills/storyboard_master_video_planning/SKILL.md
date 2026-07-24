# Video Planning

Status: `RC_OFFLINE`; canonical artifact version `1.0.0`; contract status
`IDENTITY_REGISTERED_SCHEMA_PENDING`; DV status `CLEAN_ROOM_ONLY`.

This Skill deterministically converts an approved `ProductionStoryboardPlan`,
`ProductionStoryboardPanelSet`, `ProductContextBundle`, and approved panel results
into five independent canonical artifacts:

- `VideoGenerationStoryboardMaster`
- `ShotMotionPlan`
- `VideoExecutionPackage`
- `FirstFrameMapping`
- `ReferenceRoleMapping`

The public Python surface is
`VideoPlanningInterface.build_storyboard_master(request)`. The public CLI is:

```text
python -m ai_video_platform.skills.storyboard_master_video_planning.cli build-storyboard-master <file|->
```

With `output_root`, the CLI writes the frozen `video_generation_storyboard/`
tree containing the five JSON artifacts, local review PNG, and provenance JSON.
It never calls a Provider, reads credentials, uses the network, searches Legacy,
or writes a Product Library.

The first frame is always the first shot's approved clean full-frame production
panel at the target ratio. Grids, numbers, labels, captions, other shots, contact
sheets, analysis boards, evidence boards, and replication boards are ineligible.
Approved character/product/style references may be Provider inputs; analysis-board
assets are forced to `global_structure_reference`,
`provider_execution_input=false`, and `first_frame_eligible=false`.

The five identities are registered, but their shared schemas/validators remain a
Codex-00 publication dependency. These owner-local artifacts must not be described
as formal production-ready `ContractEnvelope` exchange until that gate closes.
Planning always records `planning_provider_submission_performed: false`.

## Tests and rollback

```text
py -3.14 -m unittest -v tests.skills.storyboard_master_video_planning.test_video_planning_interface
py -3.14 -m unittest -v tests.skills.storyboard_master_video_planning.test_video_planning_failures
```

Rollback by reverting the owning commit. There is no Provider job, remote asset,
credential, or Library write to undo.
