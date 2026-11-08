# 平台

事实源：[design-server](../../docs/technical/design-server.md)、[ddd-overview](../../docs/technical/ddd-overview.md)、[design-agent](../../docs/technical/design-agent.md)、[agent_specs/README](../../duxue-server/agent_specs/README.md)。

## 目标

服务端按 Interface → Application → Domain → Infrastructure 分层。AI 调用走组件网关。Workflow / Agent / Gate / Tool 用本地 JSON 描述运行装配，领域规则留在代码。

## 状态

- 已落地：根目录 `app/` 分层、按 Context 拆 router、组件网关、声明式 Workflow、生产库 `duxue-prod`。
- `design-agent.md` 若写「目标契约，不是当前 JSON」，以文首「迁移已实现」和 `agent_specs/` 为准。
- 具体模型名以各 JSON 的 `models` 为准，不记在这里。

## 决策

- 不引入 `src/duxue` 包。ORM、OSS、鉴权、Outbox、遥测、Celery 归 infrastructure 或 workers。表名与 `duxue.*` task 名不变。
- 一个 path/method 只注册一次。共享 HTTP 辅助放 `v1/common.py`。应用装配只在 `bootstrap`。
- 组件配置随代码发布。安全裁决、答案保护、事务不进 JSON。Workflow 只编排 Agent / Gate / 代码步骤。`models` 数组顺序即尝试顺序。
- 模型返回的闭集每个取值只对应一种结果。失败映射到已有的「不可用」值，不另造同义词。
- 模型名写进 JSON。端点、密钥、超时、总开关留环境变量。`AI_MODEL_OVERRIDES` 只按组件 ID 应急覆盖，`tutoring.*` 禁止覆盖，非法值启动失败。
- JSON 组件关闭思考（`enable_thinking=false`）。线上已设的 `VLM_MODEL_NAME` / `ASR_MODEL` 不被代码默认值覆盖。实时 ASR 保持 `qwen3-asr-flash-realtime`，钉到 `2026-02-10` 会在北京空间把会话断开。
- 非 production 时服务端读、查、删 OSS 走公网 endpoint。预签名上传始终公网。生产继续内网。
- DDD 管业务语义与用例事务。Workflow 的节点、恢复、模型失败由 agent 设计管。

## 注意

- 2026-11-08 后续配置化审计（建议，未实现）：优先纳入现有Agent的修复/条件指令，以及Tool静态规范，勿按提示词片段新增Agent。代码证据：`tutor_loop.py`修复模板、`tutoring_workflow.py`图片核验追加指令、`tutor_turn.py`自述使用提示、`plan_intake.py`/`utterance_window.py`窗口指代与任务提取规则、`tutor_tools.py`的`SVG_WIDGET_GUIDELINES`。这些语义内容影响行为却未完整进入当前Prompt版本/摘要，宜随所属Agent/Tool版本管理；当前Schema只支持单个Prompt且Tool无静态内容字段，实施须先补受限契约及校验，不能直接塞未知字段。动态事实/图片授权/错误诊断、修复触发/次数/必经审核及领域写入仍归代码。摄像VLM应在[Behavior目标实现](../../docs/technical/domain-behavior.md)时纳入配置和追溯，Batch/实时传输仍由适配器执行；迁移旧Prompt不等于新观察管线落地。ASR/TTS是基础设施能力，无须为了统一目录包装成Agent。

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
