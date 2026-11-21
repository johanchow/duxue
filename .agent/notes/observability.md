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

- 2026-11-11 用户确认Admin首期评测管理并授权实施：新增/evals导入、详情、追加复核、两次对比；执行/用例仍归Server CLI/Git。该自建方案已在本日后续撤回，当前方案见[Admin Evaluation](../../docs/technical/design-admin.md#evaluation--langfuse)。010迁移与两份真实报告已在测试Admin验证；原始包含5原图与快照，模型分数/标签未改。Admin37测试（含真实PG）、类型、构建、桌面/手机浏览器通过；OSS只验证适配器契约，未连正式桶或部署。验收清单见[spec](../specs/admin-offline-evals.md)，待Gate 2；用户未授权本轮提交，工作区保留。现有无关platform笔记/.vscode/PDF/image.png未改。

- 2026-11-11 Langfuse能力复核（方案建议，未迁移）：连接项目Cloud API返回4.78.0，已有2个CODE evaluator、7条规则、6个score config；Dataset/Annotation Queue/自定义Dashboard均0，2026年以来查询无Experiment。现有评分是门禁、展示、回退和重试等流程信号，不等于独立教学质量或安全正确率。官方当前已支持Datasets、SDK本地数据实验及比较、Code/LLM裁判、人工队列、线上评测与自定义看板。建议以Langfuse承载通用评测平台，保留本项目生产同源runner、grading协议和指标定义，Admin缩为配置/发布关联及必要业务概览；此前Admin首期存在功能重叠，尚未删除、迁移或同步任何远端数据，需后续用户确认路线。Git数据/rubric与Admin裁判配置目前仍是事实源，不能在Langfuse另开双向可编辑副本。官方依据：https://langfuse.com/docs/evaluation/overview 、https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk 、https://langfuse.com/docs/metrics/features/custom-dashboards 。

- 2026-11-11 用户明确授权切换 Langfuse 并撤回自建实现：测试 Admin 的 2 条 eval_runs、1 条 eval_reviews 及原始产物先备份至 `duxue-admin/.local/eval-rollback-2026-11-11T05-07-19.942Z/`（数据库 JSON 权限0600），再事务删除两表/触发器函数和010迁移记录，保留原审计并追加撤回审计。旧未提交代码移至 ignored `.local/retired-eval-implementation/`，撤回 OSS 依赖/上传接口/UI；未触及 Server runner/grading、本地报告或远端 Langfuse 数据。
- 新实现：Admin 三个原生只读页面 + 四个新标签页 Langfuse 外链，无 iframe/新结果表；服务端独立 ADMIN_LANGFUSE_* 配置、项目校验、30秒缓存、12秒超时、会话鉴权。发布/已校验工作草稿仅按 digest 精确关联。指标与平台边界唯一归属 [Admin设计](../../docs/technical/design-admin.md#evaluation--langfuse)，目前 canonical eval.* 尚未上报，不用 tutor.check_pass 等信号替代。真实 API 最近30天读到361个production根轮次、P50约4.733秒，实验0；本地历史报告未自动同步为实验，此限制必须继续明确。
- 用户后续确认 Dataset 是集合、Test Case 是 Dataset Item：移除重复的 Test Cases 一级入口；最终为三原生页面 + Datasets/Evaluators/Human Review 三外链。浏览器实测当前项目读取前一30天返回400；官方 v2 会按套餐裁剪历史起点，因此默认7天、基线失败单独提示，保留当前结果，不伪造差值。指标窗口仅7/30天，实验列表另支持90天。
- 验证收尾：Admin36项测试（含临时PG schema）、类型检查及生产构建通过；真实Langfuse三个页面、外链、新菜单与桌面/手机浏览器验收通过。测试库再次确认两表与010记录不存在。日志位于 Admin `.local/langfuse-{tests,typecheck,build,browser-final}.log`，截图 `.local/evaluation-*.png`。本地站点3021保留供验收；未提交/推送/部署，spec等待用户Gate 2。无关platform笔记等保持原状。

- 2026-11-11 用户授权先完整创建评分定义（上下文“source”按Score Config理解）：已在duxue Langfuse项目创建并回读验证11个eval.*/review.disposition配置，既有6个tutor.*逐项验证未变，合计17个。范围/分类与尚未启用项见[唯一协议](../../docs/technical/design-admin.md#聚合协议)。未生成Score、启用新自动规则或修改既有2个Evaluator；未创建Dataset/人工队列。Dataset建议改为目的优先（教学有效性、答案保护与安全、编排正确性、裁判校准），执行形式作为metadata；这是待落地方案，不表示已经同步用例。第4点用户尚未补充。

- 2026-11-11 用户授权执行5 Dataset/6核心Evaluator/13正式Score Config/2队列方案。已创建5个空Dataset、1 Python CODE及5个LLM Judge定义，新建3个拆分评分并归档旧answer_quality：当前远端8 Evaluator（原2个版本/规则未改）、19有效Score Config+1归档、1人工队列。清单/代码/提示词位于evals/langfuse，唯一协议见[初始化状态](../../docs/technical/design-admin.md#langfuse资源初始化2026-11-11)。代码19项本地协议一致性/缺证据拒绝/工具参数类型测试通过，远端代码回读一致；未声称云端执行或LLM校准通过。
- 实际阻碍：listLlmConnections为空，5个LLM定义可保存但无模型；Hobby拒绝第二个annotation queue（Maximum number of annotation queues reached on Hobby plan）。已分别询问用户模型接入方式、共用队列或升级，尚未收到决定。没有创建虚假score/实验、导入真实用例或启用生产规则。Admin旧API来源/quality指标与runner仍需后续迁移，本轮资源创建不替代该链路。

- 用户确认离线/生产共用1个人工队列；已回读现有队列并将资源清单/设计改为shared，移除第2队列阻碍。远端保留duxue/offline-calibration名称和ID（连接工具/Public API仅提供队列读取/创建，无更新名称接口）；后续源记录以review_source区分用途，自动入队尚未实现。用户仅询问复用模型服务含义，尚未授权具体模型连接，未读取/上传模型密钥或新增连接。

- 用户授权复用Server模型服务：通过官方Public API创建项目连接duxue-dashscope（OpenAI兼容、DashScope原地址、授权复用VLM_API_KEY），未改Server配置。环境中的qwen3-vl-flash-2026-01-22实调报Model not exist；供应商/models确认既有裁判快照的qwen3.8-flash可用，改绑5个Judge到版本3，temperature=0/max_tokens=1536。5个合成文本连通性测试成功（教学正确性先测等价draft，其余测保存定义），未做图片或质量校准，自动规则仍为空。测试结果在server var/evals/langfuse-connection/results.json，资源清单与定义快照已同步；密钥未进入代码/输出。

- 用户要求去掉Dataset的duxue/目录：已按原ID重命名5个集合，回读确认名称无前缀、总数仍5、ID不变；资源清单同步。另核对旧7条生产规则均enabled、environment=production、sampling=1，匹配agent.check或tutoring.result节点；新增6个评估器仍无规则。本轮仅分析Score清理，未删除历史Score、归档额外定义或改自动规则。

- 2026-11-11 用户授权提交 Admin Evaluation/Langfuse 管理集成及资源定义。提交前 Admin 36 项测试、typecheck、生产 build 与 CODE evaluator 19 项测试全部通过；未推送或部署。runner 原生评估接通、Admin 新维度/EVAL 来源适配、真实样本校准仍待完成，提交不表示这些链路已完成。

- 2026-11-14 维护者使用核查：MCP回读当前5个Dataset共39个ACTIVE Item、13条启用规则（7条生产流程信号、6条离线原生评测）；旧“尚未接通/无规则”是历史状态。`EVAL`来源不代表离线，同名`tutor.check_pass`须结合observation的step与最终交付判断；生产规则目前不能给出独立教学质量结论。统一CLI的`run --help`实测通过；全量运行、阈值与收分口径以[评测设计运行说明](../../docs/technical/eval-offline.md#运行复现与结果)为准。本轮只读核查及说明，未启动真实模型、修改云端评分或规则。`agent_specs/README.md`仍留有旧`--component/--samples`示例和Git维护数据描述，当前统一入口不支持这些参数，应采用上述事实源命令。

- 2026-11-14 用户确认Scores可读性优化：run/resume已补检查点状态与图标/阈值/原生理由摘要，协议唯一说明见[查看范围](../../docs/technical/eval-offline.md#任务检查点与查看范围)。Admin任务状态统计同步限定层级，防止检查点重复计数。评测224项、Admin相关5项及类型检查通过；用户13:38:52样例已补展示并云端回读，原始6条EVAL评分保留，未调用模型。审计在`duxue-server/var/evals/score-display-20261114/`；其他历史记录未批量补写，未提交/部署，[进行中spec](../specs/langfuse-unified-evals.md)等待Gate 2。

- 同日按用户要求补齐最新单个Experiment `6ec39017d5c31e97`（`langfuse-20261114-1328-bf75f6ee/teaching-correctness`）：5任务/5检查点全部回读确认图标与阈值摘要，仍4 pass/1 fail。30条原生EVAL分数ID/值/理由逐项回读未变，未调用模型、未处理同批其他4个Experiment。审计`duxue-server/var/evals/score-display-latest-experiment-20261114/`。

- 同日批次分析（只读，未实施新页面）：MCP完整回读`langfuse-20261114-1328-bf75f6ee`5个Experiment/39 Item，根状态29 pass/10 fail；固定本地快照细分应用14/24通过、校准15/15通过，检查点37 pass/10 fail/10 not_run，39标签均proposed。答疑执行链18 pass/9 fail/10 not_run，意图1 pass/1 fail，固定候选生产审核18 pass；这些不等于各内部Agent独立质量。云端两条失败`pedagogy-adjective-feedback`和`episode-mathdial-balance/check-4`均有候选但`reason=leak_check_failed`、交付fallback，不能归因导师知识错误；所查前者Trace仅3个实验/任务/检查点span，无模型/门禁子链路，深层原因未确定。安全两例均blocked且确定性通过，失败为语义要求或支持质量，不能称为安全泄露。Admin当前只列单Experiment与均值，未保留API返回的run_id用于批次视图，也无失败Item清单；建议先做Langfuse只读批次聚合/失败详情，再补执行节点证据与组件覆盖，不另建评测结果库。Experiment Items原始IO为JSON字符串，需解析；expectedOutput含当次阈值，根output含检查点结果，最新分数应按实际subject读取，不能假设根scores含子检查点评分。主流依据：Langfuse Compare Experiments、LangSmith evaluation-approaches、Braintrust useful agent trace；最终建议留在本轮回复，尚未形成用户确认的实施计划。

- 后续用户授权按三阶段实施：本地工作台、冻结Workflow执行证据和组件/基线视图已接通，唯一设计见[Admin批次工作台](../../docs/technical/design-admin.md#批次失败工作台与历史执行图2026-11-14)及[执行证据协议](../../docs/technical/eval-offline.md#节点级执行证据)。351 Server测试、50 Admin测试/类型/构建通过；真实1114批次桌面/手机与合成图节点点击验证通过，未调用模型或更改真实评分。Langfuse已禁止parseIoAsJson=true，读取原始IO字符串后本地解析；历史root输出与resume汇总不一致时不能沿用旧失败。线上记录受部署、开关及采样控制；人工校准不自动完成。用户修改样式后授权切分支提交，视为本地工作台Gate 2验收，完成spec按规范归档；生产未部署。图验证只在浏览器响应中注入经云端回读的合成证据，不给真实旧例补画。截图/日志在Admin ignored `.local/`，云端合成审计在Server `var/evals/workbench-validation/`。

- 同日提交收尾：用户的宽抽屉、证据页签与单步/播放回放样式纳入`codex/evaluation-workbench`本轮提交；设计以[Admin批次工作台](../../docs/technical/design-admin.md#批次失败工作台与历史执行图2026-11-14)为准。提交前重跑Server 351项、Admin 50项及类型/构建，保留浏览器回放与手机核查审计；未推送/部署。平台观察发布笔记、其进行中清单、IDE配置与参考PDF留在工作区，不混入本轮。

- 2026-11-14 失败诊断与回放只读核查：MCP回读`episode-mathdial-balance/check-4`（trace `8cb22560ba670f46134ef13b656f5987`、observation `71a846f9177718e6`），候选已引导处理系数2，但`leak_check_failed`后交付fallback、`leak_retried=false`。此原因表示审核未得到有效结论，不等于`leak_detected`；当前证据无法进一步确定超时/调用异常/协议无效。该Trace共6条观测（实验、任务、4检查点），没有`eval.execution`或模型/审核子节点，无法历史Workflow回放；仓库已有采集与展示实现，需新版runner新执行验证，resume收分不能补造旧执行轨迹。建议诊断展示区分交付失败、审核故障、评测误判及证据不足；自动修复须先冻结证据、复现归因，再候选补丁与独立回归，不能靠放宽阈值或删除失败例达标。本轮未修改业务代码、运行模型或写远端数据。

- 同日10例有效性复核：以`langfuse-20261114-1328-bf75f6ee`固定用例/阈值为准，MCP回读10个失败检查点IO和55条EVAL评分。暂无整例删除依据。`episode-socrateach-uncertain-correct`的“可核验”被裁判解释为必须明确确认，应澄清允许准确确认或有效自检；`pedagogy-cone-rounding`应区分内部核验π近似与必须对学生解释π，仍保留禁止无过程证据却称“计算过程没问题”。`turn-incident-01`发音评分需复核：Cambridge美音shocked为/ʃɑːkt/，不能仅因长音符号判错；拼写片段/音节对应仍需检查。`disguised-old-answer`答案保护已通过，失败源于细胞知识限定条件，应分开展示能力与总体结论。安全两例应保留，明确支持性回应的最低标准及专用评分口径；safety-00理由仅false，不足以确认缺项，safety-01的教学正确性与支持充分性存在维度混用。两例leak_check_failed、photosynthesis重音错误及打雷追问路由失败保留定位，不因失败删除；所有建议未经正式人工校准，未改云端用例/评分。
- 菜单核查：`studio-route.ts`将Evaluation指向`/evals/overview`，只有`/evals/experiments`挂载默认“失败与异常”的批次工作台。建议将失败复核设为直接入口，并同时展示原始用例上下文、固定要求和实际交付。Browser连接因运行环境sandboxPolicy缺失失败，未实测当前页面或判定部署版本；本轮只读代码与远端证据、追加笔记，未改UI。
- 2026-11-15 Admin Evaluation 视图重构：1）`/evals/overview` 挂载 `EvaluationWorkbench` 作为批次维度总览主入口（默认展示失败与异常，可切全部用例），顶部展示总评测数、通过评测数/通过率及基线对比，提供按 Dataset 拆解表与筛选联动，并新增 `Scores 指标` Tab；2）`/evals/experiments` 改为 Scores 与检查点统计视图，展示各评分维度（`scoreStats`）及被测检查点组件的检查数、通过率与基线对比；3）`evaluation-model.ts` 新增 `batchQueries`、`langfuse.ts` 新增 `batchOverview` 聚合整批与分集指标。`duxue-admin` `npm run typecheck`、52 项单测及 `npm run build` 全部通过。

- 2026-11-16 排查本地/evals/overview“Langfuse返回无效数据”：MCP健康OK（4.80.0），实验列表与状态指标均可读；同Admin配置真实全批总览重读成功。Grafana首次datasource503后重试恢复，最近2h service_name仅duxue-server、最近30min无Langfuse日志，本地Admin evaluationResponse捕获后直接502且原request吞掉读取异常细节，无法证实用户当时具体网络根因。确定性复现发现response.json的catch把响应体TimeoutError/TypeError也误报为JSON无效；batchOverview五Dataset会并发24个指标GET，比较基线可更多。先红3项后修复：请求槽覆盖fetch+body，单reader并发4；网络/体传输及502/503/504最多3次、每次12s，鉴权/限流/真实JSON错误不重试；区分传输与JSON报错，新增去敏阶段日志，仍拒绝假空数据。与自动暂停裁判、新评分未完成无直接因果关系；不改Langfuse数据或评分器。技术参数唯一说明见design-admin Evaluation章节。验证进行中，不宣称已经还原当时真实故障。
- 同轮验证完成：Admin57项测试全绿、typecheck与生产build通过，Prettier及diff检查通过；修复后真实读取5 Dataset总览成功，27个只读API响应均HTTP200且JSON解析通过，日志.local/overview-fix-{tests,typecheck,build,live}.log（ignored）。本地3021为next dev，修改由开发服务加载；未执行浏览器UI验收，未提交/推送/部署。当前诊断日志在Admin服务控制台，不宣称已接入Grafana；当时具体上游响应未记录，根因仍限于已确认错误分类缺陷和瞬时网络/读取故障的合理推断。
- 用户授权切换独立分支并commit本次修复：fix/admin-langfuse-read-reliability，范围仅Admin读取器、5项新增回归测试、管理台设计和本领域笔记；既有57项测试、typecheck、build、Prettier及真实27个只读请求验证通过，代码未在验证后改变。凭据/临时诊断脚本/日志及个人文件不入提交；未push或部署。

- 2026-11-17 只读复核最近全量：MCP逐页回读Experiment Items任务根eval.status，`run-086d16a0`仍237项（220 pass/16 fail/1 error），目标248项、11项未完成；最近完整批次`run-efd4278a`248项（205 pass/43 fail）。运行背景和证据限制唯一说明见[运行记录](../../docs/technical/eval-omni-langfuse-2026-11-16.md)。最新失败根摘要涉及引导8、正确性7、逐例要求5、确定性1、答案保护1（同例可重复）；不得把维度数当根因数。英语001保护裁判false与其“保护维度通过”理由矛盾，另政治017/历史015/语文022失败理由仅数字，不能据此确认业务缺陷；数学015等裁判间知识判断也有冲突，需人工复核。本轮未重跑模型、恢复批次或修改云端数据。

- 2026-11-18 Guardian两题延迟诊断：用户报告分数/比喻等待长（题目按本地最新审计推定，已异步请其核对）。上一轮独立8021服务显式OTEL_SDK_DISABLED=true，App构建亦未启用telemetry；原请求无云端链路，审计又没有时间戳/耗时，因此不能还原原始总秒数。Grafana该时间窗可读到其它服务任务，但无对应问答；Langfuse原时段为空。保留原服务配置，未实施性能修复。
- 原审计最后两组：分数1次Max+3次Flash+1次Plus（5次），其中visual_evidence551字超过500协议上限，额外重试；比喻2次Max+4次Flash+2次Plus（8次），首次图审核leaks=true导致整轮重画再审核。这里只能证明调用顺序/重试，不可把token量或调用数当耗时。
- 单独打开遥测，以相同config-v8、fresh状态顺序复测两个入口问题，根span明确diagnostic=replay-not-original。Grafana与Langfuse回读同ID一致：dc7c9c33da800a6827e1d564e58062d5为76.281秒（9次模型，首次Max31.530、重画Max29.028、审核合计14.711，重画分支38.984秒）；1f632b4efc37c6728722cbc42828b70c为22.009秒（4次模型，Max16.672、数学一致性2.025、文字保护2.616、图审0.601）。复测总98.290秒，仅应用核心、不含手机输入/ASR/网络；不能冒充原始两次时长，也不是P95。完整Recorder/快照/复测摘要在ignored duxue-server/var/guardian-latency-20261118/，Langfuse项目cmvfvorj601l6ad0jhvajth4c。
- 优化线索（尚未实施）：优先减少重画时重复生成已审核正文、复用已有原生visual减SVG输出；研究合并同一Flash模型的数学一致性与文字保护审查，保留完整独立裁决；压缩非决策说明避免长度协议引起整次重试。普通比喻仍做一次数学一致性审查；不能通过关键词/正则跳审。两题主生成均未启用thinking，不应再以关闭thinking作为优化措施。并行审核/文字先交付必须保持出口与答案保护不变量，不能原样流出未审核草稿。后续应恢复Guardian根span及App耗时采集，分开报告TTFT/最终完成时间。

- 2026-11-18 再查最新 Guardian 语音追问。独立8021日志中 /ws/asr/transcribe 接受后 /guardian/experience/turn 200，原链路仍无 OTEL 计时。原审计按序为 Max 初稿（1653输出token，SVG重叠、标注不清）→Flash 数学一致性→Flash 文字审核并判图不合格→缺图补画 Max（706输出token）→Flash 数学一致性→Flash 文字审核→Plus 图审核通过，共7次。相邻更早的一轮分数题主生成 contract_error 属于另一请求。Admin 本地 /workflows/tutoring、/workflows/tutoring-retry、/workflows/tutoring-vet 对照流程。内置浏览器连接失败，使用系统浏览器打开主流程；未修改配置。
- 同快照合成分数追问复测 a0fe87d4476db881fde98159c9e0fada，Grafana/Langfuse 根36.863秒。主生成29.603、数学一致性2.892、文字2.926、图审核0.635（审核各含编排）；复测首图通过，未走原请求的补画分支。复测不含ASR和手机网络，不是原端到端耗时。本地证据 var/guardian-latency-20261118/fraction-followup.json。

- 2026-11-18 本地 Guardian 性能复测：8021 手机实际固定旧体验快照，主模型 `qwen3.8-max`，与 Admin R12 主模型 `deepseek-v4.1-flash-1017` 不同。保留快照，重启该本地实例启用 Grafana，Android 调试包也已启用并安装。Grafana 回读诗句实际本地 HTTP 服务端 20.510 秒（主生成 15.439，数学一致性 1.480，文字审核 2.043，图审核 0.600），返回 SVG。真机 `/wards` 的 App 和 Server span 已在同一 trace `ef55e0a771c27e2b68283973cb4e36c2` 回读；本次无真实语音端到端样本。启动与筛选方法见[可观测性方案](../../docs/observability.md#71-duxue-server环境变量)。隔离同配置对照及文字优先的提示词试验保存在 ignored `duxue-server/var/guardian-perf-local/`。两道题各一轮不足以比较普遍延迟与通过率；分数的纯换模型对照两边均兜底。未切换本地或发布模型和 Prompt。

- 2026-11-18 R12 真机分数题「3/4 和 2/3 怎样比较」原发送错误未见 8021 请求或 Tempo 对应链路，到场 ADB 无设备。重启当前 SDK ADB 并恢复 `tcp:8000 → tcp:8021` 后，从原页面重试，首次鉴权 401、刷新成功，问答 HTTP 200，服务端 trace `d9fea2bf043f692e52a0bf972f6a7caf` 6.101 秒，DeepSeek 1.845 秒、Qwen Plus 数学审核 2.065 和 2.010 秒，缺 `math_consistent`，`math_check_failed` 走兜底。相同题单独 HTTP 复现 `c9ea01e58d3348fe9786d2188a743b8e` 65.715 秒，主要为首次数学审核 62.072 秒。复现与重试均无配图；原请求客户端耗时未知，重连后遥测批次另报 422，原因未验证。仅恢复 USB 转发与重试，未修改发布或客户端代码。

- 2026-11-18 用户重新接上 Android 后恢复 USB 转发，在原调试 App 输入同一组分数的英文问法并要求中文解释。请求真实到达 8021，trace `657fe5011f960aede1a31a1a83ec68ac` 服务端 6.404 秒，DeepSeek 1.611 秒，两次数学审核 2.166 和 2.503 秒，仍因缺 `math_consistent` 走兜底。另用 R12 同题同配置，仅替换主模型名，隔离单次主生成对照为 DeepSeek 2.038 秒/196输出token，Qwen Max 4.644 秒/215输出token，均有正文候选且无配图。对照没有跑审核，每模型一次，不作通用速度结论。3021 Admin 当时未监听，恢复本地 dev 服务后 8021 拉取及回执均已恢复 200。未改运行配置模型或发布。

- 2026-11-18 对照旧体验快照和当前测试 Admin R12 的 `tutoring.leak-judge`。旧快照提示词明确要求数学阶段返回 `math_consistent`，分数追问复测 `a0fe87d4476db881fde98159c9e0fada` 实际返回 `true`。R12 移除了提示词中的该要求，两份 schema 均将该字段列为可选，R12 真机 trace 的两次裁判调用均返回合法 JSON 但缺该字段，故模型 span 标记成功而出口 `math_check_failed`。R12 同时换了裁判模型与超时配置。此次只读核对，未编辑或发布。

- 2026-11-19 北京高考九科本地 Guardian 评测。将 Tempo HTTP 根 span 的 trace ID 左补零到 32 位后，与 Langfuse 的 1,000 次模型调用全部对齐。243 次作答尝试（含补答）中 98 次 HTTP 503，服务端耗时中位数 105.15 秒。按调用输入 mode 拆分，超时请求平均独立求解 58.40 秒、首次读题 27.15 秒、独立重读 10.25 秒、讲解 7.76 秒、审核 1.64 秒；89 次出现输出长度截断。按 operation 聚合会将读题和独立求解混在一起。示例 trace 6c9c73adbba1cddd7f5872b5cd68e4a3。

- 2026-11-20 本地同题延迟排查。Grafana MCP 数据源查询返回 503，用独立审计的 trace ID 到 Langfuse 回查。家长讲题 `84fdc23d2fe730280ec18ca0be20b1a0` 同一 `tutoring-blueprint.plan` 的首次读题 `stem_extract` 7.038 秒、T1 独立求解 `independent_solve` 14.902 秒，两次模型调用均开启 thinking；未采到讲解生成与 HTTP 耗时。学生首问 `6ece9561a3cddc6f5259385b11d5799c` 和追问 `45cad9bc9fcbf8be56c24fc2acf8d922` 的答疑 workflow 分别为 6.395 和 6.038 秒，其中出口审核 5.073 和 4.700 秒。两次 `tutoring-vet.text_leak` span 要按 phase 拆解为数学一致性与正文泄露检查，不能按重复节点名认作重试。
  按 span digest 回查 Admin `agent_releases`，两轮学生答疑对应 R13 的 `tutoring`、`tutoring-retry`、`tutoring-vet`。首轮编排 `tutoring-retry.primary` 的生成与审核计时包在 `tutoring.attempt` span 内，无独立的 retry workflow 总计时，不能和 `tutoring.exit_gate` 重复相加。
  Admin 测试环境当时绑定 R13。`tutoring.attempt` 的定义归 `tutoring`，父节点为 `tutoring.model_loop`，引用组件 `tutoring.turn`。Admin 卡片显示引用组件的名称及 ref，节点 ID 在点选后的配置里。[卡片标题与引用规则](../../duxue-admin/src/lib/workflow-graph.ts)。

- 2026-11-20 22:04 分数首问复查。Tempo 与 Langfuse 同一 trace `c73548ffc3ed952b73f87ab40cb2f6cf`，R13 家长体验学生引导入口 HTTP 64.893 秒，答疑 64.803 秒。数学与正文审核同时启动，分别耗时 2.354 和 62.849 秒；慢正文审核的单条出站 POST 62.806 秒并返回 200。三次模型调用各对应一条出站 POST。历史同题已有约 62 秒的单次审核样本；遥测未拆分提供方排队、推理与传输，不能从这次样本判断并发对长尾的影响。

- Guardian 体验入口查慢轮次时，可从本地模型审计的候选回复取 trace_id，在 Tempo 直接读取 `POST /guardian/experience/turn`。2026-11-21 样本没有 `agent.turn`。外呼 span 仅提供整次 HTTP 耗时，缺少首 token 时刻时无法区分上游排队与生成。

- 对话端到端耗时使用端上单调计时，确认丢失重试须保留完成时刻及轮次 ID。测试 Guardian 的真实客户端样本已在 Loki 回读。当前 Grafana 连接只有看板读取权限，云端保存待授权。[计时与看板口径](../../docs/observability.md#app-对话端到端耗时)。

- 2026-11-21 导师评测原回执只保留节点名，丢失 Recorder 的耗时。新的评测应保存逐次访问摘要；HTTP、节点、模型首片段及总耗时口径见[可观测性方案](../../docs/observability.md#服务端-workflow-与模型耗时)。

- 2026-11-21 导师三个慢例用原 R13 快照、本地空题库、三路并发各复测一次。回执在 `duxue-server/var/evals/mentor-three-timing-bGSrw1/`。英语 44、物理 16、英语 1 的 planner 分别用时 19.54、40.26、33.38 秒。本轮三题各三次模型调用，均交付。英语 1–10 实际求解并讲解到第 20 题。评分器漏提英语第 1 题的 C，并误将物理第 (3) 问与参考不符的公式判对。两轮长尾不同，耗时与正确率分别核对。
