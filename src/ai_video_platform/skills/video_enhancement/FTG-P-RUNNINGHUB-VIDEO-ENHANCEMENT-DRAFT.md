# FTG-P — RunningHub Video Enhancement

Status: `AUTHORIZED_OFFLINE_IMPLEMENTATION`（2026-07-26 由 DRAFT 转正）。

签署记录：

- 授权人：杨少东（2026-07-26，Hermes 会话口头拍板：「授权卡从草稿转正，派 codex-05 把增强引擎装进系统，全程离线不花钱」）
- 授权基线：FTG-0-20260720-001
- 授权工作项：FT-05-003（实现真实 RunningHub adapter，全程离线开发，禁止真实调用）
- 凭证引用：`env://RUNNINGHUB_API_KEY`（实现期不读取、不验证、不索取）
- 绑定追加项（Hermes 在用户给 key + workflowId 后补录，无需重签）：
  - `workflowId` / workflow API JSON SHA-256：待补录
  - 实例类型与硬费用上限：待补录（建议上限 USD 0.20）
- 真实首单：按「首单即验收」规则执行——首次真实增强即 smoke 验收，不另开复测卡

以下原文为 2026-07-22 起草的 smoke 边界，全部继续有效。

---

# 原文（DRAFT 时期）

Status: `DRAFT_NOT_AUTHORIZED`. This file is a future gate request, not execution
authority. FT-05-002 must not call RunningHub, request a key, or resolve credentials.

## Proposed one-time smoke boundary

- Input: exactly one newly generated `OWNED` or `SYNTHETIC` MP4, no longer than 3
  seconds, low resolution, no private person or third-party mark, non-empty and at
  most 30MB, with declared bytes and SHA-256 verified locally.
- Binding: one approved `workflowId` plus exported workflow/API JSON SHA-256, fixed
  input node and operation fields, allowed values, instance type, and an attestation
  that the workflow has no unapproved third-party API or surcharge node.
- Calls: `POST /task/openapi/upload` at most once; `POST /task/openapi/create` at
  most once; `POST /task/openapi/outputs` no faster than every 5 seconds, at most
  120 polls and at most 10 minutes total; final artifact GET at most once.
- Upload/create failure: stop without changing domain, workflow, instance, fixture,
  or parameters. An uncertain result must not be retried.
- Download: approve one exact output origin and redirect policy, require video
  content type, enforce an approved byte cap, verify bytes and SHA-256, then record
  call counts, task cost time, status chain, output size, and digest.
- Disallowed unless a signed gate explicitly adds them: cancel, webhook, WSS,
  `retainSeconds`, public-object-storage input, multiple jobs, and concurrent jobs.

The proposed origin is `https://www.runninghub.ai` or one explicitly approved
equivalent origin. The legacy `/task/openapi/status` route is excluded; the public
integration documentation uses `/task/openapi/outputs` for progress and results.

## Cost draft (not a quote)

Public Enterprise Shared snapshot dated 2026-07-22: Lite USD 0.07/hour, Standard
24GB USD 0.70/hour, Plus 48GB USD 0.90/hour. These are historical public rates,
estimate-only, not a quote, and do not prove account balance, quota, discounts,
taxes, workflow/node surcharges, or instance availability. A future signed gate
must choose one instance and hard dollar cap after those unknowns are checked. A
provisional USD 0.20 ceiling may be proposed only if no additional fees exist.

## Permanent exclusions

The following Research Library assets and all derived copies are permanently
ineligible for upload or substitution:

| File | SHA-256 |
| --- | --- |
| `7665115424106892566.mp4` | `ca1c2896b7e675fb77eef61d004ffc03d6dffc568ce3edd694359033004cba11` |
| `7663913413235559698.mp4` | `b4e5a631bb3582be07a8abd22f3cd26d1c12e2d20b4ec898238632bdfaeec1c5` |
| `7655273792406637855.mp4` | `c13b6c53f551e1ca30aeb946ff05eb82b70167ae97770cc03202cb016a7ff681` |

They are third-party TikTok references with `UNKNOWN` rights and
`internal_analysis_only` lifecycle. The smoke must prove its fixture digest differs
from all three before any Provider call.

## Gate prerequisites

The signed authorization must bind the exact workflow/version, input and output
nodes, operations, fixture digest, origin and redirect allowlist, request/poll/time/
cost/concurrency limits, credential reference, cancellation decision, evidence
directory, secret-scan rule, and stop conditions. Until then provider smoke is
`NOT_AUTHORIZED` and the Protocol remains intentionally unimplemented.
