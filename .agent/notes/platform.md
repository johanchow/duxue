# 平台

事实源：[design-server](../../docs/technical/design-server.md)、[ddd-overview](../../docs/technical/ddd-overview.md)、[design-agent](../../docs/technical/design-agent.md)、[agent_specs/README](../../duxue-server/agent_specs/README.md)、[管理台设计](../../docs/technical/design-admin.md)。

## 目标

服务端按 Interface → Application → Domain → Infrastructure 分层。AI 调用走组件网关。Workflow / Agent / Gate / Tool以完整JSON描述运行装配；Admin模式优先运行不可变发布产物，本地JSON供初始化与兼容性校验，领域规则留在代码。

## 状态

- 已落地：根目录 `app/` 分层、按 Context 拆 router、组件网关、声明式 Workflow、生产库 `duxue-prod`。
- `design-agent.md` 若写「目标契约，不是当前 JSON」，以文首「迁移已实现」和 `agent_specs/` 为准。
- 具体模型名以当前Admin发布产物的`models`为准；显式本地模式才使用代码默认JSON，不记在这里。

## 决策

- 不引入 `src/duxue` 包。ORM、OSS、鉴权、Outbox、遥测、Celery 归 infrastructure 或 workers。表名与 `duxue.*` task 名不变。
- 一个 path/method 只注册一次。共享 HTTP 辅助放 `v1/common.py`。应用装配只在 `bootstrap`。
- 测试环境全部组件优先使用Admin完整发布快照，按[管理台设计](../../docs/technical/design-admin.md)加载；代码维护默认值及固定契约。安全裁决、答案保护、事务不进 JSON。Workflow 只编排 Agent / Gate / 代码步骤。`models` 数组顺序即尝试顺序。
- 模型返回的闭集每个取值只对应一种结果。失败映射到已有的「不可用」值，不另造同义词。
- 模型名写进 JSON。端点、密钥、超时、总开关留环境变量。显式本地模式下`AI_MODEL_OVERRIDES`只按组件ID应急覆盖，`tutoring.*`禁止覆盖，非法值启动失败；Admin快照生效时不允许环境覆盖发布模型。
- JSON 组件关闭思考（`enable_thinking=false`）。线上已设的 `VLM_MODEL_NAME` / `ASR_MODEL` 不被代码默认值覆盖。实时 ASR 保持 `qwen3-asr-flash-realtime`，钉到 `2026-02-10` 会在北京空间把会话断开。
- 非 production 时服务端读、查、删 OSS 走公网 endpoint。预签名上传始终公网。生产继续内网。
- DDD 管业务语义与用例事务。Workflow 的节点、恢复、模型失败由 agent 设计管。

## 注意

- 2026-11-08 管理台UI与单草稿收敛已实现：首页直接到Workflow，主要菜单Workflow/Agent/发布管理，调试记录次级；删除工作概览（无效统计/通用步骤）和操作审计页，后台审计保留。Agent编辑在页标题右上角，内容操作统一右侧，单组件去掉冗余文件栏，版本有独立详情/下载/回滚。005迁移将历史草稿只读保留并只选最近已校验的兼容未发布项为working，数据库partial unique index保证每环境最多1份working；幂等POST跨Agent/管理员共用，发布后published、放弃后archived，revision仅并发证据号。创建基线在工作草稿锁内读取；发布同时检查基线仍为当前发布，避免回滚后覆盖旧基线。调试创建时冻结base_release_id，列表显示对象名称/ID、流程或组件类型、基线与digest、结果；历史未知不猜测。近期加载回执放发布管理按需展开，与发布成功分开。17项Node/真实PG约束测试、类型检查/构建、HTTP权限/并发/单草稿/协议保护与浏览器25组件/右上编辑/版本详情/调试对象均通过。真实调试后发布R6/R7并确认加载、最终回滚R4；补齐跳转后版本详情的明确成功提示，浏览器后半流程续验通过。只操作测试库，历史记录未删除，未提交/部署生产。当前唯一设计见[管理台设计](../../docs/technical/design-admin.md)。

- 2026-11-08 用户明确扩展为全部Agent由Admin编辑发布优先生效，已纠正此前只开放Tutoring的范围限制。完整format_version=2产物包含35份JSON（25组件/9只读Workflow/1协议），所有模型Agent和Judge可调模型/Prompt/片段/已有授权工具，代码Agent/Gate及动态Tool可改展示元数据；固定实现/协议/安全边界不开放。运行目录只从产物构建，不用本地默认值补包；本地文件仅初始化和代码契约校验。Admin模式无兼容快照时AI不可用，不悄悄回退默认；未配置Admin才为显式本地模式。Companion/Planning/任务/Sprint/复盘等入口均固定快照，修复计划/任务启动缓存Prompt及复用导师备用网关的旧spec；嵌套保留外层版本。界面默认显示Admin当前发布值及版本，原v1草稿/发布保留但不兼容，需从默认值新建完整包。非Tutoring变更需该模型单元同revision/digest真实调试，不能用导师单次调试替代。已真实修改意图Prompt→先拒绝缺对应调试→意图模型成功→发布R4（35文件）→实例加载→重启恢复R4，证据在ignored `.local/full-release-smoke.json`。服务端844通过、1跳过、3 subtests；管理台16测试/类型/构建通过；浏览器真实发布R5/加载/回滚R4通过。无新增DB迁移，生产仍未接入/部署。技术事实唯一归属[管理台设计](../../docs/technical/design-admin.md)。

- 2026-11-08 管理台Agent列表按用户反馈压缩筛选区域：搜索与类型筛选并排同一行，移除分类数量及代码基线说明段，分类数仍保留在类型选项中。仅展示调整，不改变组件目录或发布协议。

- 2026-11-08 管理台三轮反馈已实现：Workflow菜单移到Agent上方，列表仅Workflow/版本/简介/配置，简介元数据仍归inventory.py。Agent菜单统一展示25项组件（10 Agent/11 Gate/4 Tool）并按模型Agent、代码Agent、模型Judge、代码Gate、Tool五类筛选；旧agents接口仍仅10项，新增components不混淆计数。此前Gate缺失来自列表过滤，并非执行配置丢失。组件详情开放已接入Tutoring的2模型Agent、2 Judge、1静态工具可调字段；动态Tool处理器不因文件在包内而标可编辑。移除配置草稿菜单，待发布列表并入发布与回滚，草稿/整包校验/调试/不可变发布机制保留。服务端838通过、1跳过、3 subtests通过；管理台15测试、类型检查/构建及Ruff通过；浏览器遍历25详情/5类型筛选/菜单顺序与表头，实际保存并Python校验导师、Judge、静态正文通过，未发布这些测试修改。无DB迁移或生产改动；唯一设计见[管理台设计](../../docs/technical/design-admin.md)。

- 2026-11-08 管理台二轮验收反馈：Agent/Workflow菜单改为table与真实独立URL详情（/agents、/agents/<id>、/workflows、/workflows/<id>），详情可直接打开/刷新。原“配置工作台”移除，Agent详情编辑明确草稿（?draft=uuid），完整包依赖/校验/调试/发布归“配置草稿”，两处操作同一份数据，无复制配置源。节点按登记定义显示模型/代码Agent、Judge/代码Gate和固定代码Action；保留有界重试回路，不强称DAG。编辑范围仍沿用首期Tutoring，其他Agent完整只读，协议/处理器/安全边界未放开。管理台15项测试、类型检查/生产构建通过，浏览器验证表格总数、9流程深链接、节点/边/完整JSON、Agent编辑保存刷新、同草稿全包校验与移动端；无新增DB迁移/生产发布。唯一设计见[管理台设计](../../docs/technical/design-admin.md)。

- 2026-11-08 管理台Gate 2反馈已补齐系统Agent总览与只读Workflow交互图；服务端目录动态返回10个Agent（7模型/3代码）、9个Workflow、11个Gate、4个Tool，作用元数据只影响展示。关联按invocation_agent/Node.ref提取；目录明确为代码基线，不能当成在线发布状态。React Flow+Dagre保留平行条件边/回路，孤立子节点parent用独立虚线，不伪造控制流；节点/边/引用组件及完整Workflow均可查看。新增目录接口先红后绿；最终服务端837通过、1跳过，管理台13项认证/真实PG/全部拓扑与平行边测试通过，类型检查/构建通过，浏览器逐一验证9个流程及点击节点/平行边、完整JSON、移动端。Next已升至16.4.5，npm audit为0；升级后重启本机两个服务。设计见[管理台设计](../../docs/technical/design-admin.md)，无新增DB迁移，未启用流程编辑或生产发布。

- 2026-11-08 Tutoring管理台首期已实现并完成本机真实联调，唯一设计见[管理台设计](../../docs/technical/design-admin.md)，启动见[README](../../duxue-admin/README.md)。已创建独立`duxue-admin-test`并应用4份迁移；Next.js负责认证/生命周期/审计，Python负责权威校验/隔离调试与单轮快照，流程及协议只读。真实题目→导师/Judge→发布R3→实例回执→回滚R1已通过，重启实例恢复R1成功；生产未启用，尚未提交/部署，Gate 2见[spec](../specs/tutoring-agent-admin.md)。私有账号/密钥与截图证据仅在ignored本地文件中。最终服务端全量836通过、1跳过、3个subtests通过；管理台3项测试、HTTP鉴权/并发/发布门禁、TypeScript/生产构建及Ruff检查通过。
- 2026-11-08 管理台联调坑：Next内部Request URL可能归一为localhost，Origin应与配置的公开origin或真实Host校验，不能把合法127.0.0.1误拒；已有回归。隔离答疑调试的题面必须同时进入主模型与Judge历史，只给Judge会得到无题面的澄清，已先红后绿修复。兼容摘要对注册集合排序，避免跨进程hash漂移；组件/片段/静态工具必须从ContextVar快照读取，禁止改全局注册表。发布证据用数据库复合FK绑定草稿/修订/digest，草稿基线持久化，旧记录不猜测回填。

- 2026-11-08 TL-IPC43CL-V2 2.0真机短测通过：系统终端完成真实RTSP→JPEG→OSS→测试库，5帧/5份OSS摘要/5条事实，队列、重连、丢弃和缺口均0；随后独立重读OSS再次核对摘要。子码流实际为H.264，基础接入兼容。Codex启动FFmpeg报`No route to host`，系统终端同一路径成功，具体系统权限/网络策略原因未证实；不得据此误判摄像头故障。机位、3h及故障验收仍未完成，状态事实见[网关spec](../specs/go-camera-gateway.md)。

- 2026-11-08 OSS现场踩坑：oss2将裸endpoint默认签成HTTP，网关正确拒绝；摄像头桶在杭州、通用endpoint在深圳，PUT返回区域不匹配。先红后绿修复公网HTTPS归一与摄像头桶独立区域配置，配置方法唯一归属[摄像头手册](../../docs/camera-setup-guide.md)。测试环境已修正，生产未动。真实凭证、图片与现场运行资料留在忽略Git的私有目录，不能提交。

- 2026-11-08 用户确认管理台首期：项目归`duxue-admin`，使用Next.js/React全栈（不新增管理台FastAPI），复用服务端数据库连接参数但数据库分别为`duxue-admin-test`/`duxue-admin-prod`，首期只操作测试环境；独立管理员、禁止注册，30秒拉取不可变发布版本/失败保留旧版/按答疑轮次固定快照/回滚按此前建议实施；不做流程编排。Next.js只管配置生命周期与管理数据，`duxue-server`拥有最终Python契约校验及隔离真实调试，禁止在JS复制答疑执行逻辑。方案进一步收敛为Tutoring完整配置包（主备模型、Judge、工具、片段/静态正文及固定协议引用）原子发布；Git拥有代码/协议/初始配置，管理台库拥有在线草稿/发布历史/环境指针，服务端缓存仅为运行副本。生产发布尚未授权；本条是实施前的确认记录，实施结果见本节最新记录。

- 2026-11-08 Tutoring管理台可行性核查（实施前历史分析，在线快照现已实现）：模型/Prompt及片段/Tool权限与静态正文/JSON输出契约已配置驱动，Python契约仍是第二层校验；不能宣称全部Flow可仅改JSON重排。`tutoring-vet`/`tutoring-retry`通过`execute_workflow`执行配置边，顶层`TutoringWorkflow.invoke → _turn`仍按Python顺序执行，`workflows/tutoring.json`兼有组件定位/观测/流程描述用途。若开放顶层可视化编排，须先补通用执行器接入与安全/事务回归。参考`sa2/multi-agent-admin/src/lib/store.tsx`为localStorage/seed演示，发布只改本地状态、调试返回预置输出；可复用页面交互，不能复用为真实运行能力。其DAG限制/任意代码文本节点不适配读学的有界重试和受控Agent/Gate/Action。建议读学首期真实配置浏览、草稿校验、隔离调试、Trace查询和Git配置导出/发布；运行时缓存及全局注册表当前不支持安全在线切换，发布沿用随代码部署。本文仅分析，未创建管理台或改变发布策略。

- 2026-11-08 已按用户确认实现具名Prompt片段及只读静态Tool，字段与运行边界唯一归属[Agent设计](../../docs/technical/design-agent.md#421-具名指令片段已实现)。修复/图片/自述/Planning窗口指令和SVG正文已迁移；逐字对照旧实现并加入固定摘要回归，主Prompt正文未变。组件版本已提升，`definition_digest`覆盖片段及引用Tool并进入CLI/Trace/离线评测；不要再只用主Prompt摘要判断完整配置相同。新增契约先红后绿，相关426通过；当前工作区服务端全量830通过、1项既有跳过，配置校验及本轮Python的F/E9/I检查通过。未部署、未迁移摄像VLM，Gate 2验收清单见[本轮spec](../specs/agent-prompt-fragments.md)。

- 2026-11-08 后续配置化初次审计（当时建议，后续实现见上条）：优先纳入现有Agent的修复/条件指令，以及Tool静态规范，勿按提示词片段新增Agent。代码证据：`tutor_loop.py`修复模板、`tutoring_workflow.py`图片核验追加指令、`tutor_turn.py`自述使用提示、`plan_intake.py`/`utterance_window.py`窗口指代与任务提取规则、`tutor_tools.py`的`SVG_WIDGET_GUIDELINES`。这些语义内容影响行为却未完整进入当前Prompt版本/摘要，宜随所属Agent/Tool版本管理；当时Schema只支持单个Prompt且Tool无静态内容字段，故需先补受限契约及校验，不能直接塞未知字段。动态事实/图片授权/错误诊断、修复触发/次数/必经审核及领域写入仍归代码。摄像VLM应在[Behavior目标实现](../../docs/technical/domain-behavior.md)时纳入配置和追溯，Batch/实时传输仍由适配器执行；迁移旧Prompt不等于新观察管线落地。ASR/TTS是基础设施能力，无须为了统一目录包装成Agent。

- 2026-11-08 配置覆盖核查：简化前`agent_specs`有9个Workflow、11个Agent（8模型/3代码）、11个Gate（3Judge/8代码）及4个Tool，定义校验与相关69项单测通过。答疑修复话术仍见[`tutor_loop.py`](../../duxue-server/app/application/workflows/tutor_loop.py)，摄像VLM的Prompt/参数仍见[`inference.py`](../../duxue-server/app/infrastructure/ai/inference.py)且不走组件目录，不能认定全部AI处理均已JSON化。随后用户授权移除计划审阅调用，现为10个Agent（7模型/3代码），见[Planning笔记](planning.md)。配置声明与代码执行/领域规则须区分。

- 2026-10-31 用户确认采集产品化路线改为标准网络摄像头 + 共享本地网关；单摄像头/家庭 Wi-Fi/电脑先验证。技术事实源已重写为 [采集设计](../../docs/technical/design-gateway.md)，旧手机实现不再作为目标方案。网关、机构能力尚未完成。注意现有心跳只反映云端连通，时间修正会改写超过24h的历史帧，元数据重试必须复用同一 OSS key。
- 测试分层见 design-server。SQLite 不能代替 PostgreSQL 约束与迁移测试。测试必须在导入应用前 `OTEL_SDK_DISABLED=true`，并 mock 外网模型。
- `alembic check` 里 LangGraph checkpoint 表与应用 ORM 的差异不要当成业务表缺失。
- `ENV_FILE` 相对 `duxue-server` 根解析。纯文本组件会把图片 part 换成占位文字。
- 答疑首字延迟在非流式下不满足 P90&lt;1.2s。流式、成本归集、provider 回退未作为完成项。

- 2026-11-01 用户授权移除旧采集实现：删除 Android 采集工程、专用 CI/发布流程及构建脚本依赖，同步接入/部署/产品导航。服务端设备、帧、校时与 OSS 能力为新网关复用，不删除兼容字段或历史迁移；网关仍待实现。移动端构建脚本用隔离的 Flutter 替身做回归测试，避免删除 Cam 后仍访问旧目录。

- 2026-11-01 家庭验证接入简化：用户确认人工配置 camera_id、RTSP 地址/本地账号与 ward_id，取消绑定码/逐摄像头云端 Token，改为预配置网关凭证与 Ward 白名单。已按仓库 DDD skill 重写 [采集架构](../../docs/technical/design-gateway.md) 为唯一目标事实源；网关、新认证/幂等上传/健康 API 与迁移均待实现。不要将旧逐设备认证接口视为支持新配置。

- 2026-11-01 网关设计复核：入口重命名为 [design-gateway](../../docs/technical/design-gateway.md)，按网关自身调用与云端间接数据关系区分领域依赖；移除本次无须新增的分析事件/任务设计，保留现有云端Memory事实契约。模型清单显式列出根实体、值对象、服务/Factory、Repository和事件；不为齐全而虚构Domain Service。

- 2026-11-01 用户要求统一聚合根命名：网关文档与仓库 DDD skill/template 使用 Aggregate Root（聚合根）及其设计，不再使用设计卡片作为表头；聚合仍表示一致性边界，聚合根表示唯一修改入口，两者语义保持区分。

- 2026-11-01 用户确认采集网关采用Go + FFmpeg + SQLite，在同仓库独立module实现；服务端继续Python。技术选型已同步[网关架构](../../docs/technical/design-gateway.md)，实现计划见[进行中spec](../specs/go-camera-gateway.md)，Gate 1已确认，现已实现；实际测试证据与家庭现场验收进度保留在该spec。

- 2026-11-01 产品目标与采图链路分析：现有 `legacy_services.analyze_and_generate` 缺模型结果时仍写默认在座字段并标记 analyzed，`RuleClassifier` 使用关键词且默认归为走神/玩耍，不能作为可靠客观报告的依据；后续行为分析设计需保留未知/缺失，开放语义交模型判断。现有每日批处理不足以支持学习中卡壳提示；无计划观察学段应与显式 StudySession 区分。另需协调 [Evaluation](../../docs/technical/domain-evaluation.md) 的自述确认后报告流程与[产品架构](../../docs/product/ARCHITECTURE.md)的零自述晚间必达要求；本轮仅分析，未修改业务行为或确认新实现方案。

- 2026-11-01 按 DDD skill 编写云端观察目标方案，事实源：[Behavior Analysis](../../docs/technical/domain-behavior.md)。窗口解释/观察日分别为事务边界；接入依赖目标证据 Query，不增加网关分析事件；求助邀请归 Study，零自述报告归 Evaluation，交互协议归 Companion。DDD 总览已改为单层 Domain 命名。设计未实现，默认阈值待标注验证；后续实施需独立 spec，勿将本轮文档或并行中的网关改动视为云端能力完成。
- 2026-11-01 用户要求 Aggregate Root 统一用域内数量及边界/职责汇总，取消逐 Root 的 Identity/子实体等清单；已同步 [DDD skill](../../.cursor/skills/domain-driven-design/SKILL.md) 和模板。观察设计已明确分钟解释、当天连续归并与故障对账的区别；帮助候选扩展为 SupportCandidate，语义判断与阈值累计分开，细节仍归对应领域设计。
- 2026-11-01 观察方案复核：术语统一为分析任务；取消独立五分钟全量比对，正常链路以原子任务/Outbox 即时推动，每分钟仅恢复到期或失效租约任务。连续性累计、语义评估与实际呈现门禁分开，详见 [Behavior §2.5/§3.2](../../docs/technical/domain-behavior.md#25-持续状态累计与帮助机会判定)；新增的是设计与伪代码，服务端尚无自动递梯子/回归邀请实现。
- 2026-11-01 用户要求直白说明持续时间筛选；已补时间顺序示例及[帮助机会模型 inputSchema/outputSchema](../../docs/technical/domain-behavior.md#帮助机会评估的-inputschema-和-outputschema)。Schema 区分真实多模态图片与 image_ref，模型只给候选建议；来源/评估版本由服务端维护，仍非已实现组件。
- 2026-11-01 用户要求在方案末尾补充[上线前测试验证方法论](../../docs/technical/domain-behavior.md#九上线前测试验证方法论)：代码规则、独立真实回放、静默观察、封闭试用分阶段验证；标注“适合/不适合/无法判断”，禁止未来信息泄漏，指标按机会去重并区分拟邀请与实际呈现。该方法尚待实施，不代表已有验证结果。

- 2026-11-01 Go网关落地：统一网关principal/白名单、幂等预约与不可覆盖OSS对象、本地SQLite/JPEG恢复、CLI及三平台包；实际入口与运行方式见[网关架构](../../docs/technical/design-gateway.md)和[接入手册](../../docs/camera-setup-guide.md)。现场RTSP/OSS长测待验收，不能以合成快照测试替代。新增迁移20261101_31只在临时PostgreSQL验证，未动开发/生产库。
- 网关迁移测试发现历史migration 02从空PostgreSQL重建Guardian表会遭遇已有FK依赖；本次未改无关旧迁移。新增迁移测试以当前schema降到30形成前一版本基线，再升31，覆盖并发幂等和Frame/Outbox原子回滚。云端新代码遵循独立聚合Repository ports，旧设备撤销入口仍属于兼容ORM路径。

- 网关数据清除边界：原 `/wards/{id}/data` 只清数据、保留Ward身份，不能仅删Device后让长期网关凭证自动重建同一登记。现保留gateway_erased停用标记并隐藏于设备列表，拒绝自动登记；保留purging上传预约作为晚到PUT的删除跟踪。不可覆盖网关URL有效期最多300s，孤儿清理晚于签名窗口。顺带修复原清除路径PlanDraft ORM被同名API DTO覆盖导致500的既有问题；均有回归测试。

- RTSP实际路径测试发现通用rw_timeout参数不适用于当前RTSP取图路径，已改用FFmpeg RTSP demuxer支持的timeout（微秒）。新增本地合成H.264 RTSP/RTP握手与解码测试走SourceFactory生产路径；lavfi解码测试不能替代RTSP协议测试，真实机型/固件仍须现场验收。

- 网关发布打包只枚举二进制、示例配置、systemd模板和依赖说明四类公开文件；不能递归打包可能已运行过的目录，避免携带照片、私有配置与凭证。Application显式决定FrameAccepted审计与既有采集事实发布，Repository负责同事务持久化。

- 2026-11-01 网关复核修复：接收Frame/审计/Outbox与删除预约同事务，重复接收先查Frame；预约清理以500行游标分页，并退役旧成功预约而不删其图片。损坏孤儿manifest只丢该帧，先写幂等缺口记录；无法确定来源不猜Ward。SQLite schema 2兼容升级保留队列，新增脱敏诊断和持久鉴权状态。
- RTSP凭证不再出现在FFmpeg argv：使用单文件concat描述经FD3管道输入，逐文件TCP/timeout选项；不落地凭证，不继承应用密钥/FFREPORT。stderr完整行脱敏后保留2KiB，丢弃超长行；诊断仅本地status/log。403取消对应源上下文并关闭FFmpeg；心跳403逐路核验。单次API401暂停上传后退避探测，成功恢复；连续3次401以78退出并关闭全部采集，systemd禁止对此自动重启。对象401/403只续签。已补各项复现/回归及带特殊字符密码的实际合成RTSP认证测试。

- 上述复核验证：服务端全量742通过，Go全量竞态/静态检查、三平台重建通过；真实摄像头/OSS长测仍待现场验收。
- 2026-11-01 摄像头帧改入 `OSS_BUCKET_CAMERA`，对象键为 `{ward_id}/{UTC日期}/{frame_id}.jpg`。`OSS_BUCKET_NAME` 继续给陪伴附件等对象。网关帧的读取、到期删除和数据清除走摄像头桶；旧逐设备帧仍在原桶。

- 2026-11-04 报告页 `frames.gateway_id does not exist` 排查：默认 `.env` 指向远端 `duxue-test`（APP_ENV=test），只读核实当时仍为 revision30，尚缺31网关帧列、32挑战表、33教学关联。打开新首页自动查询报告会立即触发缺列；不是只补33即可。所有环境更新代码后均需以与API相同配置先运行Alembic升级；`create_all`不会ALTER既有表。已补README启动顺序，本次只读诊断、未修改远端库。

- 2026-11-04 用户随后明确授权操作 `.env` 测试库，已执行 Alembic upgrade head：远端 `duxue-test` 从30升级至 `20261104_33`。只读复核全部应用表/列完整，Frame count及Task/Sprint/TutoringMessage ORM查询通过。仅测试库；生产库未操作。

- 2026-11-09 用户确认无需兼容旧数据：当前Admin产物格式3，移除手工组件/模型version，Prompt身份稳定；内部运行与观测统一用包digest，旧本地version变化不影响契约摘要。Agent/Workflow页仅显示待发布修改，不显示v/R；R只在统一发布历史。006已应用测试库，旧格式不转换/不加载。发布证据精确到主/备component，静态工具覆盖所有消费者；纯名称/简介发布无模型调用，已有发布禁止无改动重复发布。真实R8完整包、R9元数据免模型、R10备用实际调试/发布及回滚R9均通过；845服务端、19管理台测试、类型/构建、HTTP与全目录浏览器通过。当前指针R9，测试草稿保留为未发布修改；未提交/部署生产。后续质量评测/备用与Judge同模型/草稿基线整理等设计不足统一记录于[管理台设计](../../docs/technical/design-admin.md#七后续设计改进)，不在笔记复制方案。

- 2026-11-09 管理台按用户要求增加visitor/admin：007迁移原有账号admin、新用户默认visitor；会话每请求读取role/active，降权立即限制API。visitor仅查看/下载/真实隔离调试，禁止创建/保存/校验/放弃配置、发布/回滚，UI隐藏写入口、已有草稿只读。新增已发布快照调试，读取DB固定产物，不接收浏览器bundle、不新建草稿；记录明确发布基线。CLI支持user:create/user:role，setup显式初始化admin；无新增用户管理菜单。21测试/类型/构建/HTTP/管理员与访客浏览器通过，访客真实意图模型调用成功且配置不变；测试账号已停用。存储结构与权限唯一说明见[管理台设计](../../docs/technical/design-admin.md)，测试环境007已应用，生产未动。

- 2026-11-09 按用户确认优化调试首阶段：正常详情调试发布包，草稿页调试已保存完整包；未保存阻止，图与运行固定同一快照。Agent固定自身模型，不能选其他Agent，代码组件未适配明确拒绝；完整包草稿页保留集中目标选择。008保存debug来源/目标/完整bundle，结果留代码摘要及失败证据。5个Workflow接入正式入口，Tutoring/Reflection仅用隔离SQLite内存库读写；Companion/Planning暂不独立调试，审核/重试子流程随Tutoring留痕。可选ContextVar追踪实际Node/Edge、输入输出、重复尝试与失败，普通调用不启用。851服务端/22管理台/类型构建/HTTP及管理员和访客浏览器通过；真实发布Agent与Workflow/草稿Workflow/受保护Tutoring、图节点数据及自述确认隔离写入均通过，未发布配置。当前边界和下一步唯一说明见[管理台设计](../../docs/technical/design-admin.md)。测试服务8011已重启到本轮代码，生产未动。

- 2026-11-09 调试体验反馈修复：详情/草稿顶部点击打开右侧原生dialog抽屉，移动端全屏；自动焦点、背景锁滚动、Escape/返回原处，同快照保留输入与结果。Workflow结果按钮返回图检查Node；集中目标选择移入抽屉。未接入对象在入口说明实际上下文依赖并定位已有所属Workflow，不再展示笼统“适配器”提示或有效调试按钮。23测试/类型构建、抽屉桌面手机、原全目录与访客真实模型回归通过，截图已目视核对；无迁移/发布/后端执行变更。事实源见[管理台设计](../../docs/technical/design-admin.md)。

- 2026-11-09 用户授权Admin正式站点同台ECS/Docker/main自动部署：增加test/prod独立管理库和每库唯一环境指针，prod要求显式连接与HTTPS origin，本机setup拒绝prod；私有Python控制进程仅校验/调试，不持有业务DB/Redis/OSS凭据，不启动业务API。ECS容器/正式库初始化/真实联调通过，R1为正式初始发布；既有业务API来源不变。DNS/首次TLS仍待用户添加解析，未宣称域名可用；自动工作流待本分支合main生效。当前验收见[spec](../specs/tutoring-agent-admin.md)，部署唯一说明见[部署文档](../../docs/deployment.md#admin正式站点)。独立正式凭据只存ignored本机文件。

- 本次运维发现现有Worker/Beat自2026-11-08部署起持续Redis认证失败；容器Up不代表Celery可工作。证书工具安装触发needrestart自动重启Docker，后续安装用NEEDRESTART_MODE=l；未改Redis配置，API健康。证据与待验收项见上述spec。

- 2026-11-09 Admin域名验收完成：用户授权Chrome DevTools MCP配置阿里云DNS，独立HTTPS证书及自动续期演练通过，公网正式管理员登录/目录通过；当前运维事实源见[部署文档](../../docs/deployment.md#admin正式站点)。按用户最新要求未提交/推送/合并代码，自动部署待其后续合main。此前DNS待办已解除。

- 2026-11-09 用户授权ECS磁盘清理：删除51个旧Server镜像及1个无挂载失败临时容器、悬空镜像；保留全部运行镜像和两个最近Server回滚版本。磁盘从96%/剩余1.8GiB降到28%/剩余28GiB；Docker无构建缓存可清。逐一核对5个运行容器ID/镜像/启动时间不变，Admin与业务API公网health200；未改环境、业务数据或代码部署。只含镜像引用及容器身份的清理记录在ECS /root/duxue-image-cleanup-20261109.json（0600）。

- 2026-11-09 用户要求简化本地Admin配置：唯一文件改为duxue-admin/.env，显式ADMIN_DATABASE_URL，不再读取.env.local或Server连接兜底，移除本地.env.example且setup不再生成隐式环境。既有本地私密参数一次迁入0600忽略文件；Node/CLI与本地Python隔离控制入口共用.env，后者不启动业务API/配置拉取或连接业务DB/Redis。28项Node测试、类型/构建、2项Python测试、真实本地模型调试及数据库初始化通过，发布未改；生产未操作。配置与启动唯一说明见[README](../../duxue-admin/README.md#本机启动)。

- 2026-11-09 合并前只读核查：Server全量853通过/1跳过/3 subtests；生产业务库已34，Admin来源未配置且production代码仍禁自动拉取，故站点发布不会自动切换业务Agent来源。Redis ping仍认证失败，是既有后台故障；不能用API health或CI通过宣称全部线上功能正常。App Release无路径过滤，任何main push均触发APK构建/下载发布；Admin/Server工作流各自更新容器，Server Compose非滚动发布有短暂重启窗口。本次仅分析，不提交/推送/更改线上配置。

- 2026-11-09 用户授权Chrome DevTools检查并恢复线上Redis：实际为Tair Serverless KV，ECS用户名错误，改为控制台真实账号duxue后PING通过，但继续暴露MULTI未启用、Lua同槽以及BRPOP/PubSub不支持，无法承载现有Celery。验证后已将云端txn/Lua参数恢复原值。改用同ECS独立标准Redis7.4 Docker（固定digest、密码、私有网络、AOF持久化/noeviction/资源限额），只更新ECS环境和重建原版本API/Worker/Beat，不发布新代码。33条旧待处理任务已复制执行成功且保留源/私密快照；实际Celery投递消费回写、Worker pong、API/Admin health和AOF检查通过。既有Redis认证异常现已解决；运维唯一说明见[部署文档](../../docs/deployment.md#业务redis与celery运行环境)，不可重复重放旧队列。
