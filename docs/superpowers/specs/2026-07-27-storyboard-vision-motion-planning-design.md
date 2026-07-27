# Storyboard Vision Motion Planning Design

## Goal

Make in-frame storyboard motion arrows a repeatable part of
`storyboard_master_video_planning`. An execution Agent inspects every approved
Panel image. The skill then reconciles those visual observations with the
`VideoGenerationStoryboardMaster` script and deterministically plans normalized
camera and subject motion paths.

## Boundaries

- The execution Agent supplies structured `panel_visual_observations` after
  using its image-understanding capability on each approved clean Panel.
- The Python skill never calls a Provider, reads credentials, or uses the
  network.
- Visual observations and planned paths live only in sheet render metadata.
  Frozen contracts and canonical artifact semantics do not change.
- The sheet remains human-review-only and is never a video first frame.

## Input

`sheet_render_metadata.panel_visual_observations` is keyed by `panel_id`. Each
Panel observation contains:

- `confidence`: normalized confidence from 0 to 1;
- `objects`: observed hands, fingers, product, packaging, or other relevant
  subjects, each with a normalized bounding box;
- `contacts`: normalized visible interaction/contact points;
- `motion_candidates`: visually plausible normalized paths with an observed
  subject and action.

All coordinates use the Panel image coordinate space, with `[0, 0]` at the
top-left and `[1, 1]` at the bottom-right.

## Planning

The motion planner processes Panels in Master order.

1. Read Camera Motion, Subject Motion, motion path, and start/middle/end state
   from the matching Master entry and Shot.
2. Normalize the script into supported intents: camera push/pull/pan/tilt,
   press, squeeze, rotate, enter/exit, lift/release, and hold/static.
3. Match each script intent to compatible visual objects, contacts, and motion
   candidates.
4. Generate normalized arrow paths. Camera paths use role `camera`; object and
   hand paths use role `subject`.
5. Return deterministic `motion_annotations` keyed by `panel_id` for the sheet
   renderer.

The planner may use object bounding boxes and contact points to construct paths
when the visual observation identifies the relevant objects but does not supply
an exact candidate path. It must not infer object locations from script text.

## Fail-Closed Behavior

- Missing or low-confidence visual observations produce no in-frame arrows.
- Script and image conflicts produce no arrow for the conflicting intent.
- Locked/static camera instructions produce no camera arrow unless the same
  instruction explicitly includes another camera movement.
- Hold-only subject instructions produce no directional subject arrow.
- The PNG still renders with readable CAM/ACT text when arrows are omitted.
- Invalid observation coordinates fail input validation with a clear error.

## Rendering

The existing renderer consumes only the planner output. It validates normalized
paths and draws camera paths in red and subject paths in blue. It does not
inspect script keywords or invent positions.

## Tests

Owned tests cover:

- fingertip press aligned to a visible contact point;
- two-hand squeeze aligned from hand boxes toward the product center;
- product rotation and thumb press as separate paths;
- packaging entering from frame right;
- camera push-in independent from subject motion;
- low confidence, missing observations, static/hold, and script-image conflict;
- validation of normalized coordinates;
- byte-for-byte deterministic sheet rendering.

