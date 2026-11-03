---
slug: lightweight-planning-focus-sprint
created: 2026-11-03T09:26:39Z
status: draft
---

# 轻量 Plan / Task 与主动专注挑战实现

## 做什么 / 为什么

按已确认的 [计划 PRD v3.2](../../docs/product/prd-schedule.md) 改造现有实现，而非并存两套产品行为：普通任务只辅助记事与顺序提示；首页默认对话；Ward 明确开启的限时 Sprint 才展示挑战卡。保留已有数据与真实执行事实，移除旧的必填时长/钟点及未安排原因门禁。

产品规则归 PRD；执行契约见 [Study §2.4](../../docs/technical/domain-study.md#24-sprint主动专注挑战已实现待验收)，计划契约见 [Planning](../../docs/technical/domain-planning.md)。本 spec 只维护实现范围、计划和完成证据。

## 现状核对

- 服务端 `PlanningDomainService.plan_draft_view/confirm` 仍以完整时间槽为确认条件，仍生成时长、起点和 Guardian 未安排原因追问，确认时按 start_at 选项并强转 planned_minutes。
- `tasks.planned_minutes` 数据库字段已可空，主要阻塞在应用层、Agent 提示词、确认投影与客户端；不为此重复迁移已有字段。
- `day_story_pages.dart` 首页常驻今日计划横轨和未排期任务池，并有30分钟和推算起点的回退；不仅修改 `ward_pages.dart`。
- 现有任务会话接口把开始/暂停/完成独立暴露，但无独立 Sprint；无会话完成声明、结束本次而不完成任务等目标路径尚需补齐。
- Companion 当前为 v1，结构化动作只有计划确认/澄清/建议与意图选择；新挑战动作不能绕过动作签发和协议校验。

## 验收标准

- [x] A1（PRD AC-001/002/005）：仅标题即可登记并确认顺序安排；缺时长/起点不追问、不补默认值；确认不创建执行会话或 Sprint。
- [x] A2（AC-007/012）：取消未安排原因门禁；保留全部已知作业及来源，按需可查；唯一目标、本人权限、版本、幂等及历史学习记录保护继续有效。
- [x] A3（AC-003/004）：首页不常驻任务池、当前/下一项、完成按钮与普通计时；时间齐全或已有会话也不显示挑战；询问用时仅返回可靠记录。
- [x] A4（AC-006/009）：支持显式开始、暂停、继续、换项、结束本次、声明完成；未完成项与历史保留，无会话完成声明不伪造开始/零时长；视觉与离座不写完成。
- [x] A5（AC-008）：顺序不推导下一项承诺钟点；仅明确约定钟点触发 StartCue，不自动开始或催促顺序后项；保留既有日期和时区校验。
- [x] A6（AC-013）：主动 Sprint 必须有 Ward 的开始授权、实际起点和正目标时长；可无 Task；普通估时/安排和 Guardian 输入不能代开；未来约定到点只邀请。
- [x] A7（AC-014）：Sprint 开始/暂停/继续/结束幂等，单 Ward 不出现并行 active/paused 挑战；暂停不累计，收起不暂停，跨设备/断网恢复按服务端最新区间和版本，不恢复已到时旧卡。
- [x] A8（AC-015/016）：挑战到时或提前结束后卡片退场；不完成 Task、不结束原会话、不切下一项、不判失败或专注成功；跨日终止旧轮，再来一轮需新授权。
- [x] A9（AC-010/011）：历史估时建议与用时反馈按需呈现、口径可比，未知值保留；到时最多一次安全点非阻断反馈，不插答疑、不强制补弹，不新增默认主动催问。
- [x] A10：旧 Task / DailySchedule / StudySession 历史保留，API 空时间字段能被新客户端正确解析；旧草稿/旧卡失效返回可恢复结果，不误执行；新协议和数据清除覆盖 Sprint。
- [x] A11：领域/应用/API/Flutter 回归、PostgreSQL 约束与迁移验证全通过，相关全量回归和静态检查通过；未执行或受环境限制的验证如实记录，不以 SQLite 代替 PostgreSQL。

## 实现计划（Gate 1：2026-11-03 用户已确认）

### 1. 先建立回归与迁移基线

- 针对上述旧行为补有意义的失败测试，再修改实现；调整与新设计冲突的旧断言，保留授权、并发、确认版本与历史保护测试。
- 明确旧草稿/卡片失效策略；保存已有任务和会话历史，不重新解释历史预估为挑战，不补造旧任务时间来源。

### 2. Planning 从时间槽改为顺序与可选时间

- 影响：`app/application/workflows/planning_{domain_service,operations,workflow,adapter}.py`、`app/contexts/planning/domain/`、`app/api/{schemas.py,v1/planning.py}`、`app/application/queries/planning_suggestions.py`。
- 改登记、草稿、确认、修改、按需查询、取消与跨日释放；确认项不再以 start_at/end_at 过滤；取消 unscheduled_reason 门禁，目标歧义仍澄清。
- 在真实任务/安排中保留明确时间、顺序、估时意图和来源；只明确约定的起点进入提醒，旧来源不明槽位不当作新授权，不改写历史。
- 更新 `agent_specs/agents/planning.*.json`、确认 gate/workflow 与相关组件上下文，模型负责开放意图；不增加关键词/正则语义分流。

### 3. Study 执行与独立 Sprint

- 影响：`app/contexts/study/domain/`、`app/application/commands/`、`app/api/v1/study.py`、模型/仓储及新增 Alembic revision、必要 worker/调度入口。
- 补齐结束本次、显式换项及无会话完成声明；完成声明采用明确事件语义，不伪造会话区间；保持所有修改与事实发布的事务一致性。
- Sprint 独立记录 ready/active/paused/elapsed/ended/cancelled 及区间，保留可选 task/session 引用；本人授权、乐观版本、幂等和单轮约束由服务端实现。
- 到时核算覆盖调度与读取恢复，按目标截断运行时长；挑战命令和到时不调用任务完成/原会话 finish，不累加两类计时。
- 新表与约束同步 `docs/technical/design-server.md`；升级/回退只在隔离测试库验证，不对现有开发/生产库自动执行迁移。

### 4. Companion 与提醒协议贯通

- 影响：`app/application/process_managers/companion_coordinator.py`、API schema、组件声明与受控交互协议、`app/application/commands/start_cue.py`。
- 模型提议挑战意图，服务端签发确认/开始动作；自然语言的明确开始也必须经过目标、时长、本人身份和命令校验。保留 planning/tutoring/reflection 既有场景，向 Study 用例分派执行，不另造关键词路由。
- 升级协议并同步 App allow-list；新客户端可读旧消息，旧/未知动作不执行。到时通知经回复安全点去重，旧版本与已结束轮次不复活。

### 5. Flutter 首页与按需任务/挑战体验

- 影响：`lib/features/day_story_pages.dart`、`ward_pages.dart`、`home_task_card.dart`、新增 Sprint 组件/状态模块、`lib/core/{api_client,models,cue_notifications,cue_refresh_schedule}.dart` 及相关测试。
- 默认对话流与 VoiceComposer，作业/挑战安静入口；任务列表、时间和执行操作放按需详情，删除虚构19:00/30分钟回退及默认结算/复盘催办。
- Sprint 选择主题与目标时长、明确开始后展示限时卡；支持暂停、继续、提前结束、收起与再来一轮，按钮说明本轮含义，避免与“作业写完”混淆。
- 恢复前台与跨设备重新拉取状态；客户端计时仅呈现服务端已确认区间，命令失败不伪称已暂停/开始；通知不为顺序推算项发催办。

### 6. 验证、review 与落地状态同步

- 服务端按仓库 `.venv` 和 `requirements*.txt` 运行定向测试，再跑 `.venv/bin/pytest tests -q`；导入应用前禁用 OTEL，模型网关用受控替身，避免外网调用。
- 新增隔离 PostgreSQL 集成验证：迁移升降级、单活跃轮次并发、幂等、旧版本拒绝、事务回滚；沿用已有隔离数据库测试方式，不读取生产凭据作为测试依赖。
- Flutter 定向 widget/状态测试后运行 `flutter test` 与 `flutter analyze`；覆盖普通首页无任务条、空值解析、普通时间不触发 Sprint、暂停/收起/到时/恢复和旧消息兼容。
- 语义用固定模型输出走生产校验路径的契约回归，辅以代表性自然语言/多轮样本验证；不把 mock 测试当作真实模型理解质量证明。实际在线模型试用若缺环境，明确列出待验证项。
- 自查 diff、记录证据，更新产品/领域/物理设计的实现状态与对应 `.agent/notes/`，待 Gate 2 用户验收后归档 spec。

## 实现清单

- [x] 已核对产品设计、现有实现与测试入口，写好验收和计划
- [x] Gate 1：用户确认本实现计划
- [x] Planning 可选时间与轻量确认，移除旧门禁，保留保护契约
- [x] Study 执行路径、Sprint 模型/持久化/迁移/并发约束
- [x] Companion 协议、模型意图与安全反馈/提醒贯通
- [x] Flutter 默认对话首页、按需作业与 Sprint 完整交互
- [x] 定向及全量回归、PostgreSQL 验证、静态检查与 diff review
- [x] 同步文档与笔记，提交 Gate 2 验收证据
- [ ] 用户验收后归档

## 范围与边界

- 本轮覆盖已有 plan/task 行为改造及主动 Sprint，不把其他独立未实现目标夹带为完成项：云端 Behavior 分析、视觉自动邀请、零输入报告引擎等继续按各域计划推进；这里只保证无计划/无挑战不新增阻断。
- 不删真实学习历史，不因计划内容变更生成完成事实，不修改线上环境、不部署；提交/发布按用户后续指令处理。
- 2026-11-03 用户明确回复“确认”，Gate 1 已通过；按本计划实施，完成后提交 Gate 2 验收。


## 实施记录与 Gate 2 验收证据

- Gate 1：2026-11-03 用户明确确认后实施；保留 spec，待用户验收后再归档。
- 新增 `20261103_32`：Sprint/命令回执、任务时长类型与来源；旧活动草稿失效，不回填/删除真实学习历史。
- 已完成普通任务减法、显式执行、Sprint 状态/协议/客户端和数据清除；服务端真实计时替代客户端累计秒数，普通时长与挑战互不冒充。
- 自查补齐：开始后允许修订未开始项；已完成项/已开始内容保留；无时长但有钟点仍校验本地日期；有挑战记录不能物理删除任务；跨日不重开遗留挑战。
- 真实模型冒烟：普通顺序、普通起点+估时、主动挑战、完成声明、当前挑战中暂停省略表达、已知作业查询共6条通用示例均通过。只证明本次样例，不替代真实家庭持续试用。
- 实机/发布边界：本轮未部署或自动迁移开发/生产库；真实设备长时间后台、跨设备手动验收仍应在 Gate 2 关注。视觉主动邀请及 L0 报告引擎不在本轮实现范围。


### 最终自动化验证（2026-11-03）

- 服务端 `.venv/bin/pytest tests -q`：**764 passed, 1 skipped**；16.34 秒。跳过为既有网关二进制冒烟（未配置 `GATEWAY_BINARY_PATH`），与本轮无关；保留既有 FastAPI lifespan 弃用提示。
- PostgreSQL：真实隔离数据库完成迁移升级/回退、旧卡失效与历史保留、单活跃轮次并发、同命令幂等与事务回滚验证；未用 SQLite 代替。
- Flutter `flutter test`：**118 passed**；`flutter analyze`：**No issues found**。
- 变更 Python 文件未定义/重复定义检查、`git diff --check` 通过；测试导入的 pytest fixture 按实际注入用途局部注明 lint 例外。
- 最后复核统一了 StartCue 与显式任务开始路径：晚点击旧邀请也不并行计时，换项保留暂停次数、执行区间和暂停事实；完成声明及挑战仍相互独立。
- Sprint 可选绑定 Task/StudySession，仅接受本人且相互匹配的引用；到时不改绑定任务/会话，清除先删挑战再删学习会话。相关正向、越权及清除回归通过。
- Gate 2：**实现与自动化验证完成，等待用户验收**。推荐人工走一遍“标题登记 → 按需查看 → 开始挑战 → 暂停/继续 → 收起 → 到时退出”；真实设备长时间后台与跨设备手动恢复仍待人工验收。
