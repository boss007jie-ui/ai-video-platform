# 仓库内容规则（REPO CONTENT RULES）

- 拍板人：杨少东
- 生效日期：2026-07-26
- 适用范围：所有工作线（codex-00~06）、Hermes、任何向本仓库提交内容的执行者
- 违反后果：合并门禁拒绝；已提交的生成物按安全事件撤下

## 1. 永不进 Git 的内容

以下内容由 `.gitignore` 全局屏蔽，任何工作线不得绕过（不得 `git add -f`）：

1. **生成的图片/视频/音频**：`.jpg` `.jpeg` `.png` `.gif` `.mp4` `.mov` `.webm`
   `.webp` `.mp3` `.wav` `.avi` `.mkv`
2. **生成物输出目录**：`run/`、`output/`、`outputs/`
3. **产品原始素材**：`product_assets/`、`assets-local/`（本地保留，不上传）
4. **密钥与环境文件**：`.env`、`.env.*`

**唯一例外**：离线测试必需的合成夹具（如 43 字节级 `synthetic-*` 假文件、
tests/fixtures 下的确定性测试数据），已在 `.gitignore` 中用白名单放行。

## 2. 修改意见（revisions/）——进 Git

针对某产品的图/视频修改意见是**文字资产**，必须进 Git：

- 路径：`revisions/<产品ID>/YYYY-MM-DD-第N版反馈.md`
- 模板：`revisions/_TEMPLATE.md`（复制开新文件）
- 意见中引用生成物时只写**本地路径或 sha256**，不写公开链接
- 由 Hermes 负责把用户的口头意见落成文件并提交；工作线不改写他人产品的
  历史意见，只准追加新文件

## 3. 生成新产品前必读

Hermes 或任何工作线在为某产品生成新图/视频前，必须先读
`revisions/<产品ID>/` 下的历史意见，避免重复犯错。

## 4. product-knowledge 联网规则

`product_knowledge` Skill 本身保持**纯离线**（无网络代码、无凭证）。

用户需要补充产品信息时，由 **Hermes 本人**上网检索、整理成产品资料后
作为输入喂入。工作线不得为该 Skill 添加任何网络能力。

## 5. 真实 Provider 通用铁律（重申）

- 默认不联网：不显式点名真实 adapter/命令，一分钱的调用都不许发生
- 真实调用前必须有用户口头/书面点头 + 对应 FTG-P 授权卡
- 缺 key 必须在 transport 前 fail-closed
- 幂等：同一请求重复执行不得产生第二次扣费

## 6. GitHub 发布

- 远程：`https://github.com/boss007jie-ui/ai-video-platform`（**私有**）
- 默认分支：`main`（= integration 线）
- 推送前必须复跑本规则第 1 条的扫描（无媒体、无密钥）
