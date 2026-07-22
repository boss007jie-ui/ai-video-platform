# RunningHub 视频增强调研与方案 A 移交纪要

- 调研日期：2026-07-22
- 原工作项：FT-02-002（已撤销，移交 codex-05 / FT-05-002）
- 原工作线：codex-02
- 授权基线：FTG-0-20260720-001
- 当前状态：`HANDOFF_ONLY`；未实现视频增强 Skill；未执行真实 Provider 调用

## 1. 结论摘要

RunningHub 的公开资料能够证明其 ComfyUI 工作流体系可以承载视频超分、插帧、修复和带降噪参数的视频增强工作流。它不是一个具有统一增强参数和统一时长上限的单一产品接口；能力、节点、输入时长、显存实例和预计运行时间都取决于所选工作流。

建议 FT-05-002 采用“方案 A：独立同构骨架”：参照现有 `video_generation` 的安全结构，新建独立 `video_enhancement` Skill，先实现 preflight、Fake/Rejecting adapter、内存 ledger、receipt 和离线 CLI；只保留真实 RunningHub adapter 的 Protocol 接口，不实现网络、凭证或 Provider 逻辑。

本纪要不构成 Provider 授权、价格报价、配额承诺或工作流可用性保证。

## 2. 调研范围与可见性

本次只读取了无需登录即可访问的 RunningHub 官方 API 文档和 RunningHub 公开工作流页面。没有执行以下行为：

- 未登录 RunningHub；
- 未注册账号；
- 未创建或复制工作流；
- 未打开个人工作台或任务账单；
- 未索取、读取、粘贴或保存 API key；
- 未上传任何文件；
- 未创建、轮询或下载任何真实任务；
- 未调用 RunningHub 或其他第三方 Provider API。

公开可见：API 端点说明、请求/响应示例、上传格式与大小限制、Enterprise Shared 公开费率、公开工作流说明和节点列表。

需要登录或账户上下文才能确认：可调用的实际 `workflowId`、工作流 API JSON 导出、可编辑节点及其精确字段、账户 API key 类型、余额、配额、并发、排队情况、任务历史、实际账单、输出保留期，以及特定工作流在指定实例上的实际可用性和耗时。本次没有尝试绕过这些可见性边界。

## 3. 能力面

### 3.1 超分与高清修复

RunningHub 公开工作流页面展示了视频超分和修复组合。例如“Video HD Restoration & Upscaling & 2x Frame Interpolation”使用 `FlashVSRNode`、`RIFE VFI`、`VHS_LoadVideo` 和 `VHS_VideoCombine`，描述为高清修复、放大和 2 倍插帧，并允许指定放大倍率。

这证明 RunningHub 的 ComfyUI 执行面可以承载此类节点组合，但公开工作流是具体作者发布的工作流，不等于平台对所有账户、所有输入和所有时间点提供统一 SLA。

### 3.2 插帧

公开工作流中可见 `RIFE VFI` 等插帧节点。插帧可以单独存在，也可以与超分、修复和视频重新封装组合。输出 FPS 通常由工作流参数和插帧倍数共同决定，不能在未读取所选工作流 API JSON 前假设字段名称或可选倍数。

### 3.3 降噪与修复

公开的质量修复工作流展示了“noise reduction/denoise”参数，并提示更高值会增加重绘程度、可能损害口型一致性；另有工作流将低噪声视频修复与视频编辑组合。

因此方案 A 把能力命名为 `denoise_restore`，而不是承诺一个统一的传统时域降噪算法。真实 adapter 必须把该抽象映射到获批工作流的实际节点和参数，且需在 smoke 前固定工作流版本。

### 3.4 工作流类型

本工作项适合选择 RunningHub 的 ComfyUI Workflow / AI Application OpenAPI：上传输入文件，使用 `workflowId` 和 `nodeInfoList` 创建任务，再查询输出。

RunningHub 另有 Standard Model API v2，但它面向具体模型端点。本纪要不把 Standard Model API v2 与 ComfyUI 工作流 API 混为一套协议，也不建议在第一版增强骨架中同时支持两种 API 家族。

## 4. API 形态

### 4.1 上传

- 方法：`POST`
- 端点：`/task/openapi/upload`
- 请求形态：`multipart/form-data`
- 用途：上传图片、音频、视频或 ZIP，供工作流加载节点使用
- 视频响应核心字段：`data.fileName` 和 `data.fileType`

`fileName` 是 RunningHub 服务器内的相对加载路径，不是公开下载 URL。真实实现若获批，应把该值作为所选视频加载节点的 `fieldValue`，不得自行拼接外部 URL。

### 4.2 创建任务

- 方法：`POST`
- 端点：`/task/openapi/create`
- 请求形态：`application/json`
- 公开文档中的核心字段：`workflowId`、可选 `nodeInfoList`
- 公开响应核心字段：`taskId`、`taskStatus`、`clientId`，以及可能存在的 `promptTips`

文档还展示了 `instanceType`、`webhookUrl`、`usePersonalQueue` 和 `retainSeconds` 等高级选项。方案 A 首版不实现这些 Provider 参数；未来 FTG-P 必须明确是否允许以及允许值。

### 4.3 轮询输出

- 方法：`POST`
- 端点：`/task/openapi/outputs`
- 请求核心字段：`taskId`
- 用途：同时承担任务进行状态和最终输出查询

官方集成示例说明旧 `/task/openapi/status` 已不再维护，示例使用 `/task/openapi/outputs` 轮询。示例轮询间隔为 5 秒；这只是公开示例基线，真实 smoke 仍应在授权卡中固定最小间隔、最大次数和总超时。

任务运行时，公开示例可能返回包含 WSS 信息的对象；完成时返回输出列表。方案 A 的抽象 adapter 只暴露稳定的 `poll` 语义，不把 WSS 作为首版必需能力。

### 4.4 输出与下载

公开完成示例的输出项包含：

- `fileUrl`：结果文件 URL；
- `fileType`：结果类型，例如 `png`，视频工作流预期为视频类型；
- `taskCostTime`：任务运行耗时字段；
- `nodeId`：产生输出的节点。

下载形态是对获批 `fileUrl` 的直接文件获取。文档提示结果 URL 的有效期受平台规则约束，因此真实 adapter 必须在 receipt 落盘后、授权的超时与大小上限内下载，并校验内容类型、字节数和 SHA-256。不能把 `fileUrl` 当作永久资产地址。

## 5. 输入约束

RunningHub 上传文档公开列出的统一视频约束为：

- 格式：MP4、AVI、MOV、MKV；
- 单文件最大：30MB。

公开文档建议大于 30MB 时使用可公网访问的对象存储直链。方案 A 的第一轮真实 smoke 不采用该建议：fixture 必须小于或等于 30MB，并走受控上传端点，避免引入额外存储 Provider、公开 URL 生命周期和新的权利暴露面。

没有发现适用于全部 ComfyUI 视频工作流的平台统一时长、分辨率、帧率、编码器或音轨限制。公开工作流页面的限制彼此不同，例如有工作流建议 15–20 秒以内，也有特定编辑工作流限制 5 秒。这些只能作为工作流级证据，不能升级为平台统一约束。

方案 A 的时长原则：

1. preflight 要求输入声明有效的时长、宽高和 FPS；
2. 输入必须满足所选 `workflow_profile` 固定的 `max_duration_seconds`、分辨率和 FPS 上限；
3. Fake profile 使用测试专用上限，不声称代表 RunningHub；
4. 真实 profile 只能在读取获批工作流 API JSON、公开说明和一次受控 smoke 约束后固化；
5. 未固定真实 workflow profile 时，真实 adapter 必须保持拒绝。

## 6. Enterprise Shared 费率快照

截至 2026-07-22，RunningHub Enterprise Shared 公开页面展示：

| 实例 | 公开费率 | 备注 |
| --- | ---: | --- |
| Lite | USD 0.07 / 小时 | 由系统算法调度 |
| Standard，24GB VRAM | USD 0.70 / 小时 | `instanceType=default` |
| Plus，48GB VRAM | USD 0.90 / 小时 | `instanceType=plus` |

公开说明为按秒计费；并发任务按照各任务累计运行时间求和，而不是只按并发墙钟时间计费。

以上仅是公开费率快照，不是报价。以下项目必须在获批 smoke 前通过登录后的账户界面或正式授权材料确认：

- 账户实际 API 产品类型和可用实例；
- 账户级并发、排队与消费上限；
- 是否存在工作流、节点、模型或第三方 API 附加费；
- `taskCostTime` 与最终账单的换算方式；
- 余额、优惠、税费、币种和价格变更；
- 输出保留期及额外实例保留费用。

方案 A 的成本模型只能记录费率快照、实例类型、批准的最大运行秒数和估算上限，字段必须标注 `estimate_only: true`。

## 7. 方案 A：独立同构离线骨架

### 7.1 目录与依赖边界

- 新建 `src/ai_video_platform/skills/video_enhancement/`；
- 新建对应 `tests/skills/video_enhancement/`；
- 参照 `video_generation` 的安全架构和状态词汇；
- 不 import `video_generation` 的私有实现；
- 不抽取或修改共享 Core、Contracts、schema、根 CLI、pyproject 或 lockfile；
- 不实现真实 RunningHub HTTP client、SDK、凭证解析或环境变量读取；
- 不新增第三方依赖。

### 7.2 preflight 输入校验

preflight 在任何 adapter、ledger 写入或网络边界之前完成：

1. 输入是存在、可读的本地常规文件；
2. 扩展名属于 MP4/AVI/MOV/MKV；
3. 实际字节数大于零且不超过 30MB；
4. 请求声明字节数与实际文件一致；
5. 请求 SHA-256 与本地文件一致；
6. 时长、宽、高、FPS 为正值；
7. 满足所选离线 `workflow_profile` 的时长、分辨率、FPS 和操作能力；
8. 目标操作组合非空且没有未知字段；
9. 成本预算、请求数、并发、重试和超时均为正值并满足上限；
10. 幂等键存在；
11. 全部权利闸门通过。

Python 标准库不能可靠解析所有视频容器的真实时长、分辨率和编解码器。首版 preflight 校验本地文件、大小和摘要，并把媒体技术元数据视为 fixture 制作者声明；未来如需媒体探测依赖，须另走依赖审批，不能在本工作项内隐式引入。

### 7.3 权利闸门

唯一允许进入未来 Provider 路径的权利基础：

- `OWNED`：平台或项目拥有并允许交给指定 Provider 处理；
- `SYNTHETIC`：为测试专门生成并允许交给指定 Provider 处理。

以下输入必须在 adapter 之前失败：

- `internal_analysis_only`；
- `UNKNOWN`；
- 第三方参考素材；
- Research Library 资产；
- 未提供权利声明或声明与生命周期冲突的资产。

Research Library 中现有 3 个 TikTok 参考 MP4 均为 `internal_analysis_only`，绝不上传至 RunningHub 或任何第三方。未来真实 adapter 获批时，除生命周期闸门外，还应把授权卡列出的三个规范路径和 SHA-256 加入拒绝集合；拒绝集合命中必须发生在读取 Provider 凭证或构造上传请求之前。

真实 smoke fixture 必须为自有或合成素材。不得从 Research Library 复制、转码、裁剪或改名后作为 smoke fixture；派生文件继承原素材的权利限制。

### 7.4 操作组合

首版抽象操作面：

- `upscale`：按获批 profile 支持的倍率或目标尺寸放大；
- `frame_interpolation`：按获批 profile 支持的倍数或目标 FPS 插帧；
- `denoise_restore`：按获批 profile 支持的修复/降噪强度执行。

允许单项或组合，但每项必须由 `workflow_profile.supported_operations` 显式声明。preflight 不把抽象参数直接当作 RunningHub 节点字段；真实 adapter 的映射必须绑定到固定的 workflow ID、工作流摘要、node ID 和 field name。

### 7.5 adapter 缝

Protocol 语义与现有生成 Skill 对齐：

- `submit(request) -> provider_job_id`
- `poll(provider_job_id) -> state/result metadata`
- `cancel(provider_job_id)`
- `download(provider_job_id) -> artifact metadata/bytes`

首版只实现：

- `FakeVideoEnhancementAdapter`：确定性、内存内、零网络；
- `RejectingVideoEnhancementAdapter`：稳定失败、零网络。

真实 `RunningHubVideoEnhancementAdapter` 仅保留接口意图，不提供可调用类，不出现端点请求代码，不解析 key。所有公开执行结果记录 `provider_network_performed: false`。

### 7.6 ledger 与状态

采用独立的内存 ledger，复用现有生成 Skill 的行为约束而非私有代码：

- 原子保留幂等键、请求上限和并发；
- 公开读写均返回快照；
- 记录完整状态历史；
- 不确定 Provider 结果保留为 `recovery_required`；
- 相同幂等键和相同请求摘要只执行一次；
- 相同幂等键绑定不同摘要时失败。

建议状态：`submitting`、`submitted`、`polling`、`recovery_required`、`succeeded`、`failed`、`cancelled`、`timed_out`、`downloaded`。

### 7.7 CLI 面

模块 CLI 建议为：

```text
python -m ai_video_platform.skills.video_enhancement.cli inspect-enhancement-request <file|->
python -m ai_video_platform.skills.video_enhancement.cli submit-enhancement <file|->
python -m ai_video_platform.skills.video_enhancement.cli poll-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli cancel-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli download-enhancement <job-file|->
python -m ai_video_platform.skills.video_enhancement.cli recover-enhancement <job-file|->
```

CLI 读取一个 UTF-8 JSON 对象并输出一个机器可读 JSON 结果。inspect 为纯离线；执行命令在没有显式注入 Fake/Rejecting context 时失败关闭。模块 CLI 不提供 `--provider runninghub`、`--api-key` 或自动环境凭证入口。

### 7.8 receipt 字段

每次状态变化产生可审计 receipt 快照，至少包含：

- schema/version 与 receipt ID；
- authorization/work item 引用；
- request hash 和 idempotency key；
- 本地 job ID 和安全的 provider job ID 摘要；
- 输入文件名、SHA-256、字节数、格式、声明时长/宽高/FPS；
- `rights_basis`、生命周期和 fixture provenance；
- workflow profile ID、版本和摘要；
- 请求的操作组合及规范化参数；
- 实例类型、费率快照时间、最大运行秒数、估算成本和 `estimate_only`；
- 当前状态、尝试次数、时间戳和完整状态历史；
- 输出内容类型、字节数、SHA-256 和来源 URL 的安全摘要；
- `provider_network_performed`；
- `provider_execution_performed`；
- 稳定错误码、retryable 标志和经过脱敏的错误摘要。

receipt 不包含 API key、Authorization header、完整敏感 URL 查询串或本机绝对路径。真实 smoke 必须先将 receipt 原子落盘，再把安全摘要打印到 stdout。

## 8. FTG-P 一次真实 smoke 申请草案

未来 FTG-P 申请至少要固定以下内容，缺一即不执行：

### 8.1 Provider 与端点

- Provider：RunningHub Enterprise Shared / 明确账户产品；
- 精确 origin：`https://www.runninghub.ai` 或批准的单一等价域名；
- `POST /task/openapi/upload`：最多 1 次；
- `POST /task/openapi/create`：最多 1 次；
- `POST /task/openapi/outputs`：建议最小间隔 5 秒、最多 120 次、总等待不超过 10 分钟；
- 对最终 `fileUrl`：最多 1 次 GET，固定重定向、origin、内容类型和最大字节策略；
- 是否允许 cancel、webhook、WSS、`retainSeconds`：默认不允许，除非授权卡单列。

### 8.2 固定工作流

- workflow ID；
- 工作流名称、公开页面和所有者；
- 导出 API JSON 的 SHA-256；
- 输入加载节点 ID/field name；
- 每个增强操作的节点 ID/field name/允许值；
- 输出节点 ID 和预期 fileType；
- 所需实例类型；
- 工作流是否包含第三方 API 节点或附加收费节点；
- 固定版本在 smoke 当日仍可访问的确认。

### 8.3 fixture 与输入上限

- fixture 为项目自有或专门合成；
- 保存权利声明和生成 provenance；
- 明确 SHA-256、文件名、格式、字节数、时长、宽高、FPS、编码器和有无音轨；
- 建议首个 smoke 使用不超过 3 秒、低分辨率、无人物隐私、无第三方商标的合成 MP4；
- 文件必须小于或等于 30MB；
- fixture SHA-256 必须与 Research Library 三个 TikTok MP4 及其派生拒绝集合均不匹配。

### 8.4 成本与配额

草案运行时间硬上限为 10 分钟。按照 2026-07-22 公开费率快照，纯运行时估算上限为：

- Lite：USD 0.0117；
- Standard：USD 0.1167；
- Plus：USD 0.1500。

建议 FTG-P 总成本硬上限为 USD 0.20，但只有在账户页面确认无额外工作流/节点/第三方 API 费用后才可采用。若存在附加费、价格无法确认、余额/配额不可见或需更高上限，应退回重新审批，不得自动扩大预算。

申请还需确认：账户余额、API key 类型、并发配额至少 1、任务配额至少 1、目标实例可用，以及 upload/create/outputs/download 的总请求上限。

### 8.5 终止条件与证据

- 任一权利检查失败立即终止，零 Provider 调用；
- upload 或 create 失败不自动切换域名、工作流、实例或 fixture；
- 轮询达到 120 次或 10 分钟即停止；
- 输出非预期视频类型、超出大小、摘要失败或重定向越界即隔离并失败；
- receipt 先原子落盘，再打印 UTF-8 安全摘要；
- smoke 恰好执行一次，不以调试名义重复；
- 结束后运行密钥扫描，并记录调用次数、`taskCostTime`、最终字节数和 SHA-256。

## 9. 方案 A 的明确非目标

- 不在 codex-02 落视频增强骨架；
- 不实现真实 RunningHub adapter；
- 不调用 Provider；
- 不索取或存储 API key；
- 不注册或登录账户；
- 不把 Research Library 参考素材转成 fixture；
- 不支持大于 30MB 的公网直链输入；
- 不承诺统一视频时长、输出质量或 SLA；
- 不注册新业务 Contract；
- 不修改 `video_generation` 或抽取共享框架；
- 不自行开启新的工作项。

## 10. 给 codex-05 / FT-05-002 的建议顺序

1. 复核本纪要引用的公开页面在实施日仍然可见；
2. 先冻结 `VideoEnhancementInterface` 请求与 receipt seam；
3. 先写 owned tests，覆盖权利拒绝、格式/大小/摘要、workflow profile、成本、幂等和零网络；
4. 实现 preflight、Fake、Rejecting、ledger 和 CLI；
5. 运行 owned tests 与完整 offline 套件；
6. 提交 FTG-P 草案，等待独立授权；
7. 只有获批后才在独立提交中实现真实 adapter，并以自有/合成 fixture 执行恰好一次 smoke。

## 11. 公开来源

- [RunningHub API 更新日志](https://www.runninghub.ai/runninghub-api-doc-en/)
- [上传图片、视频、音频和压缩文件](https://www.runninghub.ai/runninghub-api-doc-en/api-425761099)
- [启动 ComfyUI 任务（高级）](https://www.runninghub.ai/runninghub-api-doc-en/api-276642704)
- [完整工作流集成示例](https://www.runninghub.ai/runninghub-api-doc-en/doc-7534233)
- [任务进度与 outputs 轮询示例](https://www.runninghub.ai/runninghub-api-doc-en/doc-7533305)
- [Enterprise Shared API 公开价格页](https://www.runninghub.ai/enterprise-api/sharedApi)
- [视频 HD 修复、超分与 2 倍插帧公开工作流](https://www.runninghub.ai/post/1985713971762212866)
- [带降噪参数的质量修复公开工作流](https://www.runninghub.ai/post/1973645236897492994)
- [长视频循环修复与超分公开工作流](https://www.runninghub.ai/post/1993009185663238146)

RunningHub 公开工作流页面中的能力、时长和参数描述来自具体工作流页面，用于证明能力面和工作流差异，不代表 RunningHub 平台级承诺。
