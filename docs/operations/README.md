# Operations Documentation

Hermes has one minimal local project runner at
`ai_video_platform.orchestration.hermes.project_runner`. It is a sequence guard,
not a workflow platform: it does not execute Skills, call Providers, retry work,
or ask multiple Agents to validate the same result.

It supports two fixed starts:

- `product_first`: Product Knowledge, then the shared production sequence.
- `reference_video_first`: Reference Analysis, then the same sequence.

The shared sequence is Storyboard, Panel Generation, Video Planning, one QA
review, and Video Generation. The Runner stores only `.hermes/project_run.json`,
authorizes one current Skill command, and advances once after a successful result
with at least one artifact reference. A failed result or out-of-order Skill does
not advance.

```text
python -m ai_video_platform.orchestration.hermes.project_runner start --workspace <task-workspace> --project-id <id> --entry-mode product_first
python -m ai_video_platform.orchestration.hermes.project_runner status --workspace <task-workspace>
python -m ai_video_platform.orchestration.hermes.project_runner authorize --workspace <task-workspace> --skill-id <skill> --command <command>
python -m ai_video_platform.orchestration.hermes.project_runner complete --workspace <task-workspace> --input <completion.json>
```

The completion JSON contains exactly `step_id`, `skill_id`, `command`, `status`,
`artifact_refs`, and `result`. The Runner persists only the result SHA-256 and
artifact references, not a duplicate copy of the Skill output.

All Agents must follow [REPO_CONTENT_RULES.md](REPO_CONTENT_RULES.md): one project
under `run/`, reuse `input/work/output`, and prefer descriptive filenames over
new folders.
