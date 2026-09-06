---
slug: planning-langgraph-workflow
created: 2026-09-05T00:52:22Z
status: draft
---

# Planning LangGraph Workflow spec

## 做什么 / 为什么
在已完成的 Companion Coordinator 基础上，实现第一个可对 Ward 输出内容的领域 Agent：计划协商工作流。它用 LangGraph 管理“提取意图/补齐必要信息 → 确定性校验与候选排程 → Ward 审阅 → 确认提交”的有界流程；模型只负责自然语言提取、追问和解释，不能直接写 `Task` 或 `DailySchedule`。

## 验收标准
- [ ] 安装并锁定 `langgraph` 与 PostgreSQL checkpointer 依赖；以 `WorkflowAdapter` 将 Coordinator 的 planning Run 映射为 LangGraph `thread_id`，Graph state 仅保存短期运行状态，`AgentRun` 仍是生命周期与授权权威。
- [ ] 为未确认计划新增 `plan_drafts`（含 Ward、日期、基准版本、结构化 items、待澄清字段、状态和更新时间）及迁移；确认前不修改现有 `tasks`、`daily_schedules` 或其正式状态。
- [ ] `POST /companion/turn` 对 planning Run 调用 WorkflowAdapter，并以 JSON/SSE-compatible 事件返回 Ward 可展示的追问、候选草稿或确认请求；Graph interrupt 后能够以同一 thread/Run 在下一轮恢复。
- [ ] 计划 Agent 只能经 `PlanningDomainService` 查询任务池和当前计划，执行确定性字段校验、总时长上限和最新版本冲突检测；模型输出的 draft patch 须经 Pydantic Schema 校验，不能伪造现有 task ID 或时间槽。
- [ ] Ward 的明确确认命令触发单事务提交：以最新任务/计划版本重新校验后创建/更新 `DailySchedule`、安排 `Task`、关闭 PlanDraft，并写入 `learning_events` 与 Outbox；若基础数据已变更则返回新的审阅请求而不覆盖。
- [ ] 增加 Graph 单元测试与 HTTP 集成测试，覆盖缺失参数追问、非法 task ID、超容量、暂停/恢复、确认写入、版本冲突与幂等重试；完整服务端测试、PostgreSQL Alembic upgrade/check 与 diff 检查通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/requirements.txt`、依赖锁定/部署文件：加入 LangGraph 与 PostgreSQL checkpointer，确认其与既有 `psycopg` 兼容。
  - `duxue-server/app/models.py`、`migrations/versions/<revision>_planning_workflow.py`：新增不含 Cascade 的 `plan_drafts` 与必要乐观版本字段/索引；不改写既有正式计划数据。
  - `duxue-server/app/ai_runtime/workflow_adapter.py`、`planning_definition.py`：实现强类型 `RunInvocation` / `WorkflowOutcome`、Graph registration、PostgreSQL checkpointer 与中断恢复适配。
  - `duxue-server/app/ai_agents/planning_workflow.py`、`planning_domain_service.py`：实现 Graph 节点、Pydantic 输出契约、确定性校验、草稿 patch 和确认事务。
  - `duxue-server/app/ai_runtime/model_gateway.py`、`output_validator.py`、`policy_registry.py`、`ai_policies/planning/negotiation.yaml`：封装 DashScope 结构化调用、版本化提示 Policy、输出/反伪造校验与 trace。
  - `duxue-server/app/ai_runtime/companion_coordinator.py`、`app/main.py`、`schemas.py`：仅对 planning target 接入 WorkflowAdapter，保持 tutoring/reflection 仍返回 foundation metadata。
  - `duxue-server/tests/test_planning_workflow.py`、`tests/test_e2e.py`、`.agent/notes/023-planning-langgraph-workflow.md`：覆盖与决策沉淀。
- 测试计划：
  - 用 fake ModelGateway 驱动图，先写 Graph 状态和 interrupt/resume 失败测试，不调用外部模型或网络。
  - 验证 DomainService 对 task ownership、任务池引用、日总时长、基准版本和确认幂等性的确定性行为。
  - 以 SQLite 覆盖 HTTP API 流程；以 `.env` PostgreSQL 执行实际 Alembic upgrade/check，不输出连接凭据。
  - 运行 `duxue-server/.venv/bin/pytest tests -v`、相关 Ruff、`alembic current/check` 和 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [ ] 增加依赖、PlanDraft 数据模型与迁移，并验证 PostgreSQL schema。
- [ ] 建立 WorkflowAdapter、Policy/Model/Validator 边界和可替换 fake 测试设施。
- [ ] 实现 PlanningDomainService 与 Draft 生命周期的失败测试、确定性校验和确认事务。
- [ ] 实现 LangGraph planning Graph、interrupt/resume，并接入 Coordinator/API。
- [ ] 完成集成测试、可观测 Trace、笔记和最终审阅。

## 备注

- 现有 `PlanIntakeService` 是旧的独立、非持久化入口；本 feature 不静默删除它。完成后将明确保留/迁移关系，避免双写正式计划。
- 当前领域模型没有固定事件或精确时间槽；首版只能做任务归属、字段完整性、总时长容量和版本冲突的确定性校验。若要实现“与指定时间冲突”的排程，必须先单独设计可用时段/固定事件数据模型。
