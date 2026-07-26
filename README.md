# AI Video Platform（AI 视频生产平台）

## 中文说明

### 这是干嘛的？

一句话：**把产品照片变成 TikTok 营销视频的自动化流水线。**

你给产品图和需求，它帮你走完整个流程：

1. **研究爆款** —— 用 Apify 抓 TikTok 上的爆款视频做参考
2. **分析参考** —— 拆解参考视频的分镜结构
3. **出分镜脚本** —— 规划每个镜头拍什么
4. **生成图片** —— AI 生成产品图和分镜画面（云雾 / Seedance）
5. **生成视频** —— AI 生成成品视频（Seedance）
6. **视频增强** —— 画质提升、插帧（RunningHub，接入中）
7. **质量检查** —— 每步产出自动验收

### 怎么用？

**不用写代码。** 直接对 AI 助手（Hermes）说人话，比如"帮我给这款墙板做一条
5 秒展示视频"，助手会自动拼参数、跑流程、验收结果，把成品交给你。

### 安全设计（重要）

- **默认不联网、不花钱**：所有命令默认拒绝真实调用，只有明确点名真实引擎
  才会产生费用
- **花钱前必须人点头**：每次真实生成前都要人工确认
- **不会重复扣费**：同一个请求重复执行，自动读取上次结果
- **生成的图片/视频不进本仓库**：只保存文字修改意见（`revisions/`）

### 仓库里有什么？

- `src/ai_video_platform/skills/` —— 9 个功能模块（上面流程的每一步）
- `src/ai_video_platform/cli/` —— 统一命令行入口
- `revisions/` —— 产品修改意见档案（纯文字）
- `docs/operations/REPO_CONTENT_RULES.md` —— 仓库内容规则

### 当前状态

离线验证完成（555 项测试全绿）。Seedance 出图、出视频已接通可用；
RunningHub 视频增强接入中。首次真实使用按"受控首单"规则验收。

---

## English

### What is this?

One line: **an automated pipeline that turns product photos into TikTok marketing
videos.**

Give it product images and a goal, and it walks the whole production line:

1. **Viral research** — pulls trending TikTok videos via Apify as references
2. **Reference analysis** — breaks down the storyboard structure of references
3. **Storyboard** — plans every shot
4. **Image generation** — AI product images and panel frames (Yunwu / Seedance)
5. **Video generation** — AI video clips (Seedance)
6. **Video enhancement** — upscaling and frame interpolation (RunningHub, in progress)
7. **QA review** — automatic acceptance checks on every artifact

### How do you use it?

**No coding required.** You talk to an AI agent (Hermes) in plain language —
e.g. "make a 5-second showcase video for this wall panel" — and the agent
prepares the inputs, runs the pipeline, verifies the output, and hands you
the result.

### Safety design

- **Offline by default**: every command refuses real provider calls unless an
  adapter is explicitly named — zero accidental spend
- **Human approval before spend**: every real generation requires explicit
  confirmation
- **Idempotent**: re-running the same request replays the local receipt, never
  double-charges
- **Generated media never enters this repo** — only text revision notes
  (`revisions/`) are committed

### Repo layout

- `src/ai_video_platform/skills/` — 9 capability modules (one per pipeline step)
- `src/ai_video_platform/cli/` — unified command-line entry point
- `revisions/` — per-product revision notes (text only)
- `docs/operations/REPO_CONTENT_RULES.md` — repository content rules

### Status

Offline verification complete (555 tests green). Seedance image and video
generation are wired and usable; RunningHub video enhancement is being
integrated. First real use follows a controlled first-order acceptance rule.
