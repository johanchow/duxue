# 可观测与评测运行

事实源：[observability](../../docs/observability.md) §7.1、[eval-offline](../../docs/technical/eval-offline.md)。

## 目标

三端用 OpenTelemetry 进 Grafana。Langfuse 只做可选的 AI observation，不增加 Alloy 或额外容器。离线评测按类型分目录、一例一个 JSON。教学回复使用独立语义评分，当前为未校准实验结果，人工复核仍保留。

## 状态

- 已落地：服务端 OTLP、App relay、Langfuse 进程内 processor、对话正文、步骤 input/output、`tutoring.attempt`、配置身份、`conversation_replay/` 的 `run-conversations`。
- 早期「Langfuse 不收儿童对话」已被授权的正文上报取代。旧 trace 不回填。
- 未做：Langfuse Dataset、自动发布门槛、儿童数据留存与删除策略。评测图片资产不进 Git。

## 决策

- Langfuse 是同一 `TracerProvider` 上的第二个 span processor，默认关闭。只导出 `duxue.agent` 与 `duxue.model`，不收 HTTP、SQL、Redis、Celery 或异常原文。
- `session_id` 用 `ConversationThread.id`。`AgentRun.id` 只作 metadata。trace 是单轮，Session 是连续对话，Run 是一次 Agent 任务。
- 根 `agent.turn` 记孩子可见输入和最终展示回复。generation 记实际消息与原始回复。被拒草稿不能当成已展示内容。图片进 Langfuse Media。Grafana 侧把图片字节换成占位符。
- 每条 observation 写 `kind`、`kind_id`、`kind_version`，并保留 `workflow_id`、`node_id`。目录外模型调用记 `external`。同一 Agent 的主模型与备用模型靠 `component_id` 区分。
- Grafana 与 Langfuse 共用采样器。要看完整 Session 需采样率 1.0。环境变量表若写 `0.2`，以 §7.1.1 和部署环境实际值为准。
- 模型原文还可写独立审计文件，不进 stdout / Loki。生产必须同时设置 `AGENT_DEBUG_AUDIT_ENABLED=true` 和 `AGENT_DEBUG_AUDIT_PATH`。
- 评测按类型分目录。真实多轮不能拆成孤立 `problem/reply`。v2统一输出pass/fail/error/not_run；未校准评分的pass不代表正式教学质量达标。
- Flutter 不持有 Grafana token，只带 `traceparent` 把白名单事件送到 `/telemetry/client-events`。relay 未配 Grafana 也先校验 payload，每主体 120 条/分钟。

## 注意

- 业务 `AgentTrace` / Checkpoint 在 PostgreSQL，不是 OTEL trace。
- Grafana MCP 配置含令牌，不能提交。
- 首次联网回放不能当成主生成已修好。

- 2026-11-11 评测成熟度核查：当前40份数据/77检查点全部proposed，无confirmed；7份仍含正文/配图字面匹配。`expect`已有确定性判分，生产泄露Judge及其标签对照不等于独立教学质量grader；教学正文仍pending_review。适用于故障冒烟/回归，尚不能作为教学质量或发布达标证据。优先人工金标与中文多模态语义rubric，再校准独立评测Judge；工具轨迹/状态副作用和token/调用预算需配套采集，不能只加JSON字段。方法事实源仍见[离线评测设计](../../docs/technical/eval-offline.md)。本轮validate及评测器141项测试通过，未调用真实模型；仅审查及记录，未实施新grader或修改标签。

- 同日按用户确认补充判分目标协议，唯一设计见[§五](../../docs/technical/eval-offline.md#五判分原则与协议)。本轮仅文档；数据仍为v1，新grader、v2迁移及校准均待实施，不扩充用例。

- 同日用户授权改造全部评测并要求遇待确认即停：已整理[实施清单](../specs/eval-grading-v2.md)。预检发现新裁判模型/配置来源未定，且正式语义结论需先人工校准；暂停代码与数据迁移，待确认接入及阶段安排。

- 用户已接受先输出未校准实验评分、校准后再用于正式质量判定的安排；裁判配置接入方式仍待确认，实施继续暂停。

- 2026-11-01 旧 Android 采集工程已移除，可观测文档改为待实现的共享 Python 网关；不再配置采集 APK 的 BuildConfig 或签名。网关心跳与摄像头采集健康需分别验收，不能把云端连通当作有新帧。

- 2026-11-01 更新：采集程序已采用Go实现，本地结构化日志/status与云端逐摄像头心跳快照已落地；OTEL导出未接入。实际配置和健康语义见[网关架构](../../docs/technical/design-gateway.md)，不要将旧的“Python网关待实现”历史记录当作当前状态。

- 2026-11-11 后续实施：用户已确认独立Admin裁判接入及未校准实验评分策略。40份文件/77检查点已迁移v2（50个教学检查点带语义评分），原始证据、状态与proposed标签逐文件核对未变；正常加载拒绝v1，迁移须显式提供整理后的rubric。独立评分只读实际交付正文/配图/读音卡和截至本轮历史原图，生产门禁放行不能冒充评分。工具轨迹来自真实调用，缺失轨迹为error；缺图/缺快照为error，多轮中止后逐项not_run并保留分母。无执行结果时outcome为空，不伪造fallback。首次评分不自动重试，成本延迟单列；token预算待采集。唯一协议与旧Admin包升级步骤见[评测设计](../../docs/technical/eval-offline.md)。本轮未发布Admin或调用真实模型；全量测试的6项PG集成受UID501初始化环境阻塞，待用户选择处理方式，spec保留待验收。

- 同轮连接核查：Server `.env`配置的RDS测试库可连接、SELECT 1成功；故障来自pytest未配置TEST_GATEWAY_DATABASE_URL后启动临时PG的initdb/UID501，不是数据库连接失败。当前账号无建库权限；数据库集成会执行迁移/降级，须专用可清空测试库，未操作共享业务测试库。

- 2026-11-11 v2首次全量真实模型运行：用户授权40份/77检查点各1次，R9导出加本地兼容升级（math不启用）及独立评分裁判，模型/原Prompt不变、未发布Admin。51通过/15失败/1异常/10因多轮中止未执行，2/5段多轮完整通过。逐项7个error分布4个检查点，3点另有fail故汇总为fail。报告索引 `duxue-server/var/evals/grading-v2-live-20261111-072341/README.md`，原始结果与快照/代码摘要可追溯。读音卡被裁判当隐藏字段、伪装事实索旧题答案被质量裁判要求直答等疑似误判待人工校准；不要将自动失败直接等同产品缺陷，未重抽或改标。

- 同日失败修复：grader v2.2补同例语义要求、实际展示面和输出协议；旧快照刷新须显式`--refresh-grader`，不改模型与其他组件。冻结40份原教学回复重评，3个明确评分上下文误判转通过；其他改分不自动算修复。候选复用已验收r72选图Prompt，专项9次/27断言通过；完整40份/77点重跑63 pass、11 fail、3 not_run，数学/读图/任务切换/生产判官仍失败。诊断与配置、原始日志唯一索引：`duxue-server/var/evals/grading-v2-fixes-20261111/REPORT.md`。原报告不覆盖、标签与阈值不改、Admin未发布。相关315测试通过；排除用户暂缓的PG集成后989通过/1失败/1跳过，失败为数学执行器macOS额外环境键断言，不宣称全绿。完整批改原始输出还发现1100 token预算下JSON截断；预算实验单列，不能与数学正确性混淆。

- 输出预算实验补充：本地主/备用生成器上限6000 token、60秒定向跑图片批改，7次原始输出均完整JSON，但3个生成检查点仍失败，另有候选basis超300字及错误数学反馈；不将预算变更当整例修复、不发布。精确配置、失败回复与诊断仍见同一报告。

- 用户在知悉上述失败与未完成验收后授权切换分支并本地提交；分支`codex/eval-grading-v2`。提交包含v2协议、40份数据迁移、裁判接入/修复、回归测试与文档，保留进行中spec；本地运行报告/候选快照仍在ignored var目录。排除无关platform笔记、.vscode、参考PDF及image.png，不推送或发布，不据提交宣称全量通过。
