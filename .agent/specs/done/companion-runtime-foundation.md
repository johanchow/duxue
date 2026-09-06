---
slug: companion-runtime-foundation
created: 2026-09-04T15:37:48Z
status: done
---

# Companion Runtime Foundation spec

## 做什么 / 为什么
实现 `design-agent.md` 的第一阶段：将统一聊天入口收敛为一个确定性优先、可审计的 Coordinator，并通过受权、裁剪的 MemoryFacade 构造最小上下文。它只负责路由和创建/恢复 Run，绝不生成领域回复、调用模型工具或写入长期理解；计划协商、答疑 ReAct 和复盘工作流留给后续独立 feature。后续领域 Workflow 使用 LangGraph 作为受限图运行时；Coordinator 通过 `WorkflowAdapter` 的 Pydantic 契约调用它，领域生命周期和事实仍由本服务持有。

## 验收标准
- [ ] Ward 可通过受鉴权的 `POST /companion/turn` 在同一线程创建或恢复唯一一个 planning / tutoring / reflection Run；响应包含可审计的 `RouteDecision`、Run 引用和最小 `ContextEnvelope` 元数据，不包含领域 AI 回复。
- [ ] Coordinator 严格按安全/权限 → 已验证 `route_hint` → 正常续接的 focus Run → 明确意图 → 澄清的优先级路由；明确的新意图不能被 focus Run 覆盖，含多个未指定优先级的领域意图必须返回 clarify，且不能创建多个 Run。
- [ ] `conversation_threads`、`agent_runs`、`agent_checkpoints` 和 `agent_traces` 持久化线程版本、focus Run、领域状态、最小上下文引用和审计信息；每个 thread 的 version 以乐观锁拒绝并发陈旧 turn，所有 FK 保持默认 `NO ACTION`。
- [ ] ContextBuilder 只能通过 `MemoryFacade.resolve_context` 读取记忆；Facade 对 Ward/Guardian/System 角色、visibility、类型、时间窗口、item/token budget 做授权和裁剪，返回证据引用而不是完整原始对话、完整画像或未经验证的 Candidate 结论。
- [ ] Context Snapshot/Trace 只保存 Policy/模型版本、受权 context refs、裁剪后的上下文和耗时等可回放元数据，不保存模型隐式推理；此次不接入模型、SSE、自由工具或 Agent 间自动委派。
- [ ] 新增单元和 HTTP 集成测试覆盖路由优先级/澄清、线程版本冲突、跨 Ward 隔离、MemoryFacade 的 visibility 与预算裁剪，以及 Trace/Run 的持久化；服务端完整测试和迁移检查均通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/models.py`：新增 Coordinator 的线程、Run、可恢复 Checkpoint 和 Trace 模型；使用原生 UUID、唯一/索引约束与默认无 Cascade 的外键。
  - `duxue-server/migrations/versions/<revision>_companion_runtime_foundation.py`：仅追加建表的 Alembic revision，不修改已有事实或记忆表。
  - `duxue-server/app/ai_runtime/`：新增受限类型契约、确定性 Intent Router、Coordinator、ContextBuilder 与 Trace repository；不在这些模块中直接查询记忆表。
  - `docs/technical/design-agent.md`：记录 Coordinator/WorkflowAdapter/LangGraph 的调用边界、checkpoint 所有权以及主要类关系 UML 和一次 turn 时序图。
  - `duxue-server/app/memory.py`（或拆分的 `app/memory/` 包）：保留现有事实写入接口，并新增 `MemoryContextRequest`、`MemoryBundle` 和 SQLAlchemy MemoryFacade，实现角色/visibility、结构化筛选、预算和证据投影。
  - `duxue-server/app/schemas.py`、`duxue-server/app/main.py`：声明并接入 Ward 的 `/companion/turn` 请求/响应；验证 route hint 与目标 Ward，返回 JSON 协调结果（SSE 留给领域 Agent 实现）。
  - `duxue-server/tests/test_companion_runtime.py`：新增纯路由、Facade 和端到端 API 覆盖；必要时扩充现有 fixtures。
  - `.agent/notes/022-companion-runtime-foundation.md`：沉淀 Coordinator、Checkpoint 与 MemoryFacade 的实现边界和已知演进点。
- 测试计划：
  - 先为 Router/Coordinator 写失败测试，覆盖各优先级、明确意图覆盖 focus Run、并列意图澄清和乐观锁冲突；实现后转绿。
  - 用 SQLite HTTP fixture 验证 Ward 鉴权和跨 Ward 隔离，创建/恢复 Run、Trace 和 checkpoint 的数据形态。
  - 为 MemoryFacade 构造不同 visibility/status 的 episodic memory、signals 与 profile，验证只召回 Active/有权项目，并在 item/token budget 下稳定截断和返回 evidence refs。
  - 运行 `duxue-server/.venv/bin/pytest tests -v`、`ENV_FILE=.env duxue-server/.venv/bin/alembic check`（或仓库既定等价命令）及 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 定义并迁移线程、Run、Checkpoint、Trace 的 ORM 数据结构。
- [x] 为 Runtime 与 MemoryFacade 建立 Pydantic 契约和失败测试。
- [x] 实现确定性 Router、Coordinator、ContextBuilder、Trace 持久化和 `/companion/turn`。
- [x] 实现受权/裁剪 MemoryFacade，接入 ContextBuilder。
- [x] 完成集成覆盖、迁移/全量测试、diff 审阅与实施笔记。

## 备注

- 首个可交付入口返回编排结果而非 AI 文本，符合 Coordinator 不生成领域答案的边界。各领域 Agent 的 SSE 输出将在其 own Run runtime 完成后接入。
- 现有 `tutoring_sessions` 仍是答疑领域会话的事实源；`agent_runs.run_ref` 仅保存其受权引用，不能复制工作状态或聊天全文。
