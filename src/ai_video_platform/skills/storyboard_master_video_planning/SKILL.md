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

## Vision-guided Sheet motion

Before invoking the CLI for a review Sheet, the execution Agent must inspect
every approved clean Panel with its image-understanding capability. It must
cross-check the visible hands, product, packaging, contact points, and plausible
motion paths against the matching Master Shot script. Script text alone is not a
visual observation and must never be used to invent object coordinates.

The Agent writes observations under
`sheet_render_metadata.panel_visual_observations`, keyed by `panel_id`:

```json
{
  "S01-P01": {
    "confidence": 0.95,
    "objects": [
      {"id": "product", "kind": "product", "bbox": [0.2, 0.3, 0.8, 0.85]},
      {"id": "finger", "kind": "finger", "bbox": [0.65, 0.05, 0.95, 0.45]}
    ],
    "contacts": [
      {"actor_id": "finger", "target_id": "product", "point": [0.64, 0.48]}
    ],
    "motion_candidates": [
      {
        "role": "subject",
        "action": "press",
        "subject_id": "finger",
        "points": [[0.88, 0.16], [0.64, 0.48]],
        "confidence": 0.92
      }
    ]
  }
}
```

Coordinates are normalized to the clean Panel with `[0, 0]` at top-left and
`[1, 1]` at bottom-right. Canonical candidate actions are `push`, `pull`,
`pan_left`, `pan_right`, `tilt_up`, `tilt_down`, `press`, `squeeze`, `rotate`,
`enter_left`, `enter_right`, `exit_left`, `exit_right`, `lift`, and `release`.

The Skill validates the observations, reconciles them with Camera Motion,
Subject Motion, and Shot states, then automatically produces renderer-only
`motion_annotations`. Missing, low-confidence, or incompatible visual evidence
produces no in-frame arrow; readable CAM/ACT text remains. The Skill never calls
the vision model itself and never writes observations or arrows into canonical
Master semantics.

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
