---
slug: realtime-behavior-observation
created: 2026-11-12
status: draft
---

# 近实时行为观察与晚间交付

## 做什么 / 为什么

用户已认可新设计及「分钟多图视觉解释 → 持续观察 → 按需语义评估 → 确定性邀请门禁」流程，并要求实现。本文将其落实为跨 Server、App、Admin 配置契约的可验收计划；Gate 1 已于2026-11-12由用户确认，进入实现。

唯一设计源：[Behavior](../../docs/technical/domain-behavior.md)、[Study §九](../../docs/technical/domain-study.md#九观察触发的求助邀请目标扩展)、[Evaluation §九](../../docs/technical/domain-evaluation.md#九零输入晚间交付目标扩展)、[Companion](../../docs/technical/domain-companion.md)、[Admin](../../docs/technical/design-admin.md)。测试方法以 Behavior §九为准，本文只记录实施与验收。

## 范围与实施选择

- 完成采集证据 Query、近实时分析、观察日发布、帮助机会评估、Study 邀请、Companion/App 呈现及回执、零输入晚间报告和 Guardian 展示。
- 复用 Go 网关、OSS、PostgreSQL、Celery；新增受控证据元数据以支持归属版本、提交有序接收游标和已知观察范围。不另建消息系统或训练模型。
- 15 秒扫描新接收证据；已结束的 60 秒窗口基础分析一次，默认四张原图，按需上下文总计最多八帧。帮助评估独立预算，最多最近四分钟十六帧；历史补传不得触发当前提醒。
- 分析与帮助评估各自作为受版本管理的模型组件，可使用同一模型；模型和 Prompt 从 Admin 完整发布或显式导出读取。代码不新增生产默认 Prompt 配置源。补齐现有发布包升级/导入工具、校验、调试及兼容性说明；兼容旧运行环境，未升级不能影响已有答疑配置加载。
- 默认 shadow；完整实现 opt-in 卡片与受控短语音的送达路径。真实提醒的扩大启用遵循文档标注回放、静默观察、封闭试用门槛，工程测试通过不等于模型质量通过。
- 2×2 拼图与空座像素差分为可关闭适配器优化，基础路径使用独立多图。拼图不预先承诺省 Token 或提高准确率；空座短路严格限定上一相邻窗口已确认 away、归属相同、齐帧无缺口，并增加周期模型复核，防止误判无限延续。默认关闭，真实回放验证后再启用；将此运行选择同步回设计唯一归属。
- 本轮交付本地代码、迁移、验证工具与测试证据；生产发布、正式环境迁移和真实儿童主动提醒不在本轮自动启用范围。实机/真实模型质量验收未执行时明确保留未完成项。

## 验收标准

- [ ] 新 Frame 按提交有序游标发现；跨页并发提交、重试、历史补传不漏不重；采集时归属版本不可由当前绑定替代。未知观察范围不编造覆盖率。
- [ ] 每个完成窗口只创建唯一基础任务；输入变化产生新版本；调用模型在事务外。真实多图 image parts、时间与受控帧引用齐全；越权、非法来源/区间、非法输出被拒绝，失败不填「在座」或「走神」。
- [ ] Window、分析任务、接收游标，以及解释与归并任务分别原子提交；租约恢复、重试、旧 attempt fence、删除 fence、Outbox/inbox 去重可验证。
- [ ] 持续状态跨窗口累计；活动/unknown/missing 互斥且时长守恒；缺图中断、重复帧、多来源、跨日边界不重复计时。
- [ ] ObservationDay 即时追加不可变 revision；来源未变不发布；基础观察不受帮助模型失败阻塞。
- [ ] 帮助语义评估只在满足文档持续状态和新鲜度条件后调用，同来源缓存；无把握无候选，无关键词语义兜底。
- [ ] 邀请默认 shadow；两类邀请共用额度、冷却、单活动邀请和连续候选去重；无通道/未授权/答疑中/过期不呈现；实际送达前重读最新观察。
- [ ] App 协议版本、卡片、opt-in 陪伴通道租约、短语音播放及真实回执贯通；重复拉取/断线恢复不重复播报；抑制/中断不报告播放完成；接受不自动创建题目或会话。
- [ ] 启用报告的 Ward 即使无计划、自述、图片也在本地截止时间生成 partial 报告；默认 Asia/Shanghai 21:30，缺来源不写零值或伪造掌握凭证。
- [ ] 报告来源版本锁定，补传追加版本，乱序来源不降级；Guardian 当前绑定授权即时生效；旧报告保留历史语义，不伪造来源。
- [ ] 每 Ward 单一分析/报告写入路径；新路径启用后旧每日批处理及手动分析入口不得覆盖新结果或将缺结果标记 analyzed。切换、回滚与旧客户端兼容均有测试。
- [ ] 组件配置/管理目录/隔离调试/完整发布包兼容通过；模型与 Prompt 版本可追溯；日志不输出图片、签名 URL、孩子原话。
- [ ] 自动化测试通过；生产同源稀疏图片回放工具可用，输出人工标签对照、unknown/missing、误/漏邀请、延迟、成本及版本证据；真实样本验收单独记录。

## 实现计划（Gate 1：计划确认）

### 1. 契约、数据与证据接入

影响：`app/contexts/behavior_analysis/domain/`、`app/application/ports/`、`app/application/queries/`、`app/infrastructure/persistence/models.py`/新增仓储、`gateway_repository.py`、`gateway_ingestion.py`、新 Alembic 迁移；必要时网关健康/配置协议与对应 Go 测试。

先实现 ObservationWindow/Day、策略、Outcome、Coverage 值对象与不变量。新增持久任务、来源版本、接收水位和受权 Evidence Query；接收序号必须按提交顺序安全消费，不能直接以数据库 sequence 最大值充当完成水位。对历史帧显式回填或标记归属未知，不能猜测历史绑定。观察范围来源不足时先返回 unavailable。

测试：领域计时与版本；真实 PostgreSQL 迁移升降级、提交乱序、分页、唯一约束、事务回滚和跨 Ward 授权。

### 2. 视觉组件与近实时 Worker

影响：`app/application/commands/behavior_observation.py`、AI adapter、`app/agent_specs/` 注册/契约/调试、Admin 包升级工具、`app/workers/celery_tasks.py` 及专用任务模块、现有 Outbox 基础设施。

增加可见活动与帮助机会两个模型组件，受控图片输入、结构化输出和一次格式修复；固定发布快照。实现扫描 → 开窗/持久任务 → claim → 模型 → 接受解释/归并任务 → Day revision/Outbox。恢复仅扫到期/租约失效/未派发任务，不每分钟全量重算。指标区分接收、排队、推理、发布延迟和图像成本。

测试：多图请求契约、模型失败/非法引用、部分窗口、历史补传、同输入去重、提交前后崩溃、失效 Worker、删除在途结果；独立配置升级/旧包兼容回归。

### 3. 持续状态与 Study 邀请

影响：Behavior assembler、帮助评估适配器、`app/contexts/study/domain/`、Study command/query/API、持久化预算及事件消费者。

实现按文档阈值的连续状态计算、语义候选及缓存，HelpOfferBudget 的 reserve/present/respond/expire；shadow 记录拟决策和抑制理由，不产生真实呈现。所有开放语义由模型判断，代码负责协议、计时、频率、授权和新鲜度。

测试：阈值边界、缺口、恢复学习、晚到帧、重复/乱序事件、并发超额、StartCue/答疑优先、接受/拒绝/超时。

### 4. Companion 与 Ward 实际送达

影响：Companion command/API/协议与交互注册、App 核心 API/模型/首页/卡片/音频播放及测试。

升级受支持交互协议；实现 support channel 开启/续租/关闭、PresentHelpOffer、实际卡片/语音回执和受控动作。保持安静首页，用户主动开启后才启用陪伴提示；语音只使用随 App 发布的受控资源。未运行真实客户端播放验证，不标记实机交付通过。

测试：服务端授权与回执重放、协议兼容；Flutter widget/状态测试覆盖前后台、静音、播放中断、断网恢复、过期/重复邀请和 VoiceComposer 聚焦。

### 5. 零输入晚间报告与 Guardian 展示

影响：Evaluation domain/command/query/API、报告仓储、截止任务/交付 job、`duxue-app/lib/features/guardian_report_view.dart`、报告页及模型。

实现 ReflectionReport 不可变版本、来源向量、报告收件索引；独立于 Frame 的启用 Ward 截止调度。优先确定性事实模板保证模型失败仍交付，模型措辞通过组件网关且受时间预算约束；时长与微验证结论来自权威来源。Guardian 展示截止时刻、覆盖/缺失、当前版本及历史。

测试：无图/无计划/无自述、所有依赖失败仍交付、真实为零与未知分离、晚到追加版本、来源不倒退、解绑立即拒绝、收件重建与重复通知。

### 6. 切换、回放与完整验收

影响：旧 `legacy_services.py`/批处理入口及查询兼容、回放 CLI/数据集协议、部署/可观测性文档、相关领域文档与笔记。

新增按 Ward 切换与防双写；历史报告明确旧口径。实现生产同源离线图片时序回放和 shadow 观察诊断，真实资产仅受权引用且不提交仓库。保留真实模型版本、运行参数和人工标注状态；不能用模型自评替代人工验收。

测试：Python 全量、真实 PostgreSQL 故障/并发、Flutter test/analyze；若改网关跑 Go test/race/vet，若改 Admin 跑其既有测试/类型/构建。回放固定模型端到端验证与真实视觉质量分别报告。真实多晚、机位、故障和容量验收需实际样本与设备，不能用自动化替代。

## 实现清单

- [x] 核查领域设计、代码差距、配置发布约束与相关笔记。
- [x] 填写范围、验收与实现/测试计划。
- [x] Gate 1：用户确认具体实施计划。
- [x] 证据接入、领域模型与数据库迁移（本地；未迁移正式环境）。
- [x] 视觉组件、发布兼容、持久任务与观察日核心链路。
- [x] 帮助评估、Study 策略与默认 shadow。
- [x] Companion/App 卡片、固定语音资源、回执代码与 widget 测试（实机见下方）。
- [x] 晚间报告、版本与 Guardian UI。
- [x] 旧链路防双写、帧级回放工具、全量自动化验证（邀请质量指标待真实样本）。
- [ ] 真实图片人工复核与静默观察，记录启用限制。
- [ ] Gate 2：用户验收，沉淀并归档。

## 当前验证记录

本轮已修改 Server/App，新增迁移35及配置/回放工具。生产环境未迁移、未发布；本地现行 Admin 发布未替换。

- 服务端最终全量1101 passed、1 skipped、3 subtests passed（43.09秒）；包括模型失败时unknown/missing区分。旧上传API不再猜测采集归属后，API契约追加复跑28 passed。
- 最新专项：59 passed，包含真实 PostgreSQL 升降级、提交排序与模型列映射，以及观察领域/任务/API契约。
- Flutter全量160 passed；`flutter analyze` 无问题。覆盖默认不请求通道、opt-in真实卡片回执、到期撤下与历史报告选版。手机真实音频完成/中断仍未验收。
- 四张合成空白图经过真实多图适配器、配置网关和模型输出校验，qwen3.8-flash返回4个unknown，耗时7.89秒。配置digest `99e3569348f86fbc66a79564bdd35d455d0bb14d42bae3ef81cb076d697a114e`。本地证据 `duxue-server/var/observation/synthetic-smoke.json`，候选完整导入包 `duxue-server/var/observation/import-release.json`（均不提交）。原环境配置的两种qwen3-vl-flash名称返回model_not_found；候选包显式采用已有视觉组件的可用模型，不设置运行时兜底。
- 运行边界统一维护于[Behavior §十](../../docs/technical/domain-behavior.md#十实现与运行状态2026-11-12)，物理表映射已同步服务端设计。

### 尚未完成（不能标记全量验收通过）

- 真实图片人工标签、独立验收样本、两类邀请误/漏率、多晚shadow、手机音频与断网实机验收、现场负载P95。需要实际采集的新归属证据和设备，不以合成图/fixture冒充。
- 拼图与空座差分可选优化尚未接入，当前始终为独立多图路径。
- 回放现支持人工帧级混淆计数；实际邀请质量与金额输出保持unavailable，待真实标签/计费证据接入。
- 答疑更早日期补写尚缺事件驱动报告更新；当天每5分钟复核。既有答疑过程凭证不冒充独立微验证通过。
- Gate 2尚未请求或通过；spec保持进行中，不归档、不声称全部质量门槛已满足。


## 2026-11-13 Admin 单源补齐（用户已明确要求实施）

沿用已确认范围，不再次请求 Gate 1。将两个视觉单节点扩展为含真实 code/LLM 节点的 Workflow；观察归并、邀请决策、报告发布注册为 code Agent Workflow。生产和隔离调试使用相同 execute_workflow，完整配置包拥有流程，代码仅提供受控处理器与安全约束。补齐目录、debug capabilities、升级包和回归，保留默认 shadow。Admin导入仅建立可审阅草稿，不自动发布正式环境。

- [x] Workflow/Agent 契约、目录和配置升级。
- [x] 正式调用经过统一 Workflow runtime。
- [x] code/LLM 与 Workflow 隔离调试及测试。
- [x] Admin 草稿导入与验证（测试草稿74，已发布R9不变）。


本轮Admin改造验证：Server全量1117 passed、1 skipped、3 subtests passed；Admin41测试、typecheck、生产build通过。5个Workflow通过真实HTTP隔离调试，两条视觉Workflow各1次真实模型请求，其余0次；图片为显式合成空白图，不代替摄像头样本。实际8个Agent、5个Workflow目录读取已验证，code单独调试、配置节点身份切换、禁止跳过授权校验、非法handler拒绝、模型debug运行参数传递均有回归。测试工作草稿ID `84199a20-b77d-4918-a869-c4b9a26a58b2`，revision74；未发布、未改正式环境。测试Admin本地3021和Executor8011已启动，页面HTTP200。内部HTTP调试证据在 `duxue-server/var/observation/admin-workflow-debug.json`（不是Admin发布所需的持久debug_run记录）；发布前仍需在管理台按当前修订完成调试门槛。


## 业务主流程与发布准备（2026-11-13）

- [x] 用户要求：整合behavior-observation主图、保留独立晚间报告，补Workflow筛选。
- [x] 生产任务按图阶段恢复，阈值分支/呈现复核测试通过；Server1117、Admin43测试通过。
- [x] 测试草稿76及两个Workflow HTTP调试通过；未发布。
- [x] 真实摄像头短测5帧，失败重试恢复；多人/遮挡仍不确定，不宣称质量通过。
- [x] 正式Admin R1只读导出，并生成独立升级提案（不覆盖测试或正式账号）。
- [ ] PR/CI及分阶段Admin部署。
- [ ] 正式配置审阅、调试/发布与回执。
- [ ] Server部署、迁移35、指定Ward shadow验收。

正式R1目前缺少数学/评测契约，直接合并自动Server部署会遇配置预检问题；需先更新Admin控制进程与配置再部署Server。本机SSH无访问权限，GitHub Actions认证可用。真实长测/独立质量验收继续保留原待办。
