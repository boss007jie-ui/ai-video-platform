# Storyboard Chain Root CLI and Hermes Invocation

Authorization: `FTG-0-20260720-001`

## Public target commands

| Target syntax | Owner | Status |
|---|---|---|
| `ai-video-platform viral-research search` | Viral Research & Asset Collection | `TARGET_NOT_ROUTED` |
| `ai-video-platform reference-analysis analyze-storyboard` | Reference Analysis | `TARGET_NOT_ROUTED` |
| `ai-video-platform storyboard derive-production-panels` | Storyboard | `ROUTED` |
| `ai-video-platform image-panel generate-panels` | Product Image / Panel Generation | `ROUTED` |
| `ai-video-platform video-planning build-storyboard-master` | Storyboard Master / Video Planning | `ROUTED` |
| `ai-video-platform video-generation run` | Video Generation | `ROUTED` |
| `ai-video-platform qa-review review-artifact` | QA / Review | `ROUTED` |
| `ai-video-platform qa-review review-composition` | QA / Review | `ROUTED` |
| `ai-video-platform seedance-nz-image generate-product-image` | Product Image / Panel Generation | `ROUTED` |
| `ai-video-platform seedance-nz-image generate-panel` | Product Image / Panel Generation | `ROUTED` |
| `ai-video-platform seedance-nz-image inspect-generation-request` | Product Image / Panel Generation | `ROUTED` |
| `ai-video-platform seedance-nz-video execute-seedance-nz` | Video Generation | `ROUTED` |

The ten Root CLI targets above are executable through the
thin root dispatcher `python -m ai_video_platform.cli`; the dispatcher only
forwards to each owner's public CLI or public interface. Viral Research and
Reference Analysis remain `TARGET_NOT_ROUTED` in this bounded wave. The
machine-readable target manifest is `ai_video_platform.cli.root.ROOT_CLI_TARGETS`.

## Hermes call protocol

For each step Hermes must:

1. Resolve input contract references and validate exact identity, supported version, provenance, approval state, and producer authority.
2. Invoke only the owning Skill's public CLI. Hermes must not import a Skill adapter, domain module, or Provider client.
3. Require structured output references and a `SkillExecutionEvent`; never infer a missing artifact from `TaskContext` or a similarly named file.
4. Validate every returned business artifact against the registry and its published schema gate before forwarding it.
5. Pass immutable artifact references to the next consumer; never rewrite an owner-produced artifact.
6. Stop the affected step on unsupported version, missing ProductContextBundle, unapproved panel, identity mismatch, provenance gap, or role misuse.

The eight commands can be invoked independently. Composition is an explicit Hermes sequence, not an implicit global pipeline.

## Required composition order

```text
viral-research search                         (optional)
reference-analysis analyze-storyboard
storyboard derive-production-panels
image-panel generate-panels
video-planning build-storyboard-master
qa-review review-artifact / review-composition
video-generation run
seedance-nz-image generate-product-image | generate-panel | inspect-generation-request
seedance-nz-video execute-seedance-nz
qa-review review-artifact / review-composition
```

QA placement is policy-driven and may run after every artifact. It does not change producer ownership.

## Video execution gate

Before invoking Video Generation, Hermes must verify all of the following:

- `VideoGenerationStoryboardMaster`, `ShotMotionPlan`, `VideoExecutionPackage`, `FirstFrameMapping`, and `ReferenceRoleMapping` share the same approved planning revision.
- shot order and panel order agree;
- every execution panel is approved and belongs to `ProductionStoryboardPanelSet`;
- the first-frame asset is one clean full-frame panel with the target video ratio;
- analysis boards and contact sheets are absent from first-frame and provider-input roles;
- any analysis board is at most `global_structure_reference` and is explicitly non-executable.

Real Provider execution remains governed by its separate authorization and release state. This document grants no network, credential, or Provider authority.
