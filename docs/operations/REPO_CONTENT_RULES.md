# 仓库内容规则（REPO CONTENT RULES）

- 拍板人：杨少东
- 生效日期：2026-07-26
- 适用范围：所有工作线（codex-00~06）、Hermes、OpenCode，以及任何向本仓库写入内容的执行者
- 违反后果：合并门禁拒绝；已提交的生成物按安全事件撤下

## 1. 项目文件怎么放

- 所有项目都放在 `run/<YYYYMMDD-简短项目名>/`。
- 不得在仓库根目录新建 `task-*`、临时目录或生成物。
- 一个项目默认只用 `input/`、`work/`、`output/` 三个子目录：
  - `input/` 放用户提供的视频、图片和请求。
  - `work/` 放中间 JSON、帧、脚本和收据。
  - `output/` 放给用户审阅或交付的成果。
- `PROJECT.json`、`status.json`、`provenance.json` 和 `run.log` 直接放项目根目录，不为它们单独建文件夹。
- 优先用文件名区分阶段和版本，例如 `ra-analysis-v01.json`、`storyboard-sheet-v02.png`、`video-final-v01.mp4`。
- 除非 Skill 强制要求固定路径，不按 Skill 名称反复新建子目录。
- 临时文件使用系统临时目录；任务结束后清理空目录和缓存。

## 2. 产品库怎么放

产品素材根目录是 `C:\Users\boss0\Desktop\05-项目文件夹\AI Video Product Library`。

- 一个真实产品或产品家族使用一个顶层目录。
- 颜色、SKU、视角和版本优先写进文件名：`<product>-<sku>-<color>-<view>-vNN.ext`。
- 只有同一 SKU 有大量素材、文件名已无法清楚区分时，才为 SKU 新建子目录。
- `_shared/` 只放多个产品共用的文档或素材。
- `_system/` 只放 Product Knowledge 的 metadata、audit、locks、snapshots 等内部数据；Agent 不得手工改写。
- 调用 Product Knowledge CLI 时，`--library` 固定指向产品库的 `_system` 目录。
- 项目中间图、故事板、视频和日志留在 `run/`；只有用户确认的产品原始素材和定稿信息才进产品库。

## 3. 永不进 Git 的内容

以下内容由 `.gitignore` 全局屏蔽，任何工作线不得绕过（不得 `git add -f`）：

1. **生成的图片/视频/音频**：`.jpg` `.jpeg` `.png` `.gif` `.mp4` `.mov` `.webm`
   `.webp` `.mp3` `.wav` `.avi` `.mkv`
2. **生成物输出目录**：`run/`、`output/`、`outputs/`
3. **产品原始素材**：`product_assets/`、`assets-local/`（本地保留，不上传）
4. **密钥与环境文件**：`.env`、`.env.*`

**唯一例外**：离线测试必需的合成夹具（如 43 字节级 `synthetic-*` 假文件、
tests/fixtures 下的确定性测试数据），已在 `.gitignore` 中用白名单放行。

## 4. 修改意见（revisions/）进 Git

针对某产品的图/视频修改意见是**文字资产**，必须进 Git：

- 路径：`revisions/<产品ID>/YYYY-MM-DD-第N版反馈.md`
- 模板：`revisions/_TEMPLATE.md`（复制开新文件）
- 意见中引用生成物时只写本地路径或 sha256，不写公开链接
- 由 Hermes 负责把用户的口头意见落成文件并提交；工作线不改写他人产品的历史意见，只准追加新文件

Hermes 或任何工作线在为某产品生成新图/视频前，必须先读
`revisions/<产品ID>/` 下的历史意见，避免重复犯错。

## 5. Product Knowledge 联网规则

`product_knowledge` Skill 本身保持**纯离线**（无网络代码、无凭证）。

用户需要补充产品信息时，由 **Hermes 本人**上网检索、整理成产品资料后
作为输入喂入。工作线不得为该 Skill 添加任何网络能力。

## 6. 真实 Provider 通用铁律

- 默认不联网：不显式点名真实 adapter/命令，一分钱的调用都不许发生
- 真实调用前必须有用户口头/书面点头 + 对应 FTG-P 授权卡
- 缺 key 必须在 transport 前 fail-closed
- 幂等：同一请求重复执行不得产生第二次扣费；已有 taskID 或 pending receipt 时必须恢复原任务

## 7. Agent 开工前检查

1. 确认当前项目目录在 `run/` 下。
2. 优先复用 `input/work/output`，不新建平行目录。
3. 先查找同名或同哈希文件，不重复拷贝大文件。
4. 若必须例外建目录，在 `PROJECT.json` 中用一句话说明原因。

## 8. GitHub 发布

- 远程：`https://github.com/boss007jie-ui/ai-video-platform`（**私有**）
- 默认分支：`main`（= integration 线）
- 推送前必须复跑第 3 节的扫描（无媒体、无密钥）
