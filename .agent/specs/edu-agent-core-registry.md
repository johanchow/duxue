---
slug: edu-agent-core-registry
created: 2026-11-28T08:40:00Z
status: awaiting_acceptance
---

# Slice 1：统一 Skill/Tool 注册表、EduAgentOrchestrator 骨架与成人只读学情

契约事实源：[Agent 配置设计](../../docs/technical/design-agent.md#44-tool-契约与统一注册演进升级)、[Conversation Domain](../../docs/technical/domain-conversation.md)、[ArtifactWorkspace Domain](../../docs/technical/domain-artifact-workspace.md)。

## 验收标准

- [x] 新增权威 Schema：`duxue-server/app/application/agent/schemas/tool.schema.json` 与 `skill.schema.json`（兼容既有 Admin v3 发布包）；启动期与单元测试双向校验注册 Handler 与代码级 `RolePolicy` 角色硬上限，越权放宽直接 fail-fast。
- [x] 在 `duxue-server/app/application/agent/` 实现共享基础设施：`RolePolicy`、`ToolRegistry`、`SkillRegistry` 与 `ToolExecutor`（鉴权 → 入参 Schema 校验 → `agent.tool` / `agent.skill` Langfuse Span 埋点 → 结构化错误翻译）。
- [x] 实现初始 5 Skills / 11 Tools Composition Root（`app/application/tools/core_tools.py`），原有 1600+ 服务端单测零破坏。
- [x] 实现 `EduAgentOrchestrator`（支持 `Default General Mode` 仅挂安全只读基础工具 + `agent.load_skill` 渐进式注入 Skill `instructions`、挂载专属 `tools[]` 与登记 `required_gates[]`），并提供 `/v1/agent/catalog`、`/v1/agent/turns`、`/v1/agent/runs/{id}/events`（SSE）与 `/v1/agent/runs/{id}/cancel`。
- [x] 多对话线程支持成人显式关联只读 `context_ward_id`（`POST/PATCH /v1/conversations` 强校验 `GuardianWard` 绑定，Ward 传参返回 `403`），注册 `ward_context.read_summary` 只读 Tool（对学生 `Memory` / `TutoringSession` 零写入）。
- [x] `Evaluation` 与 `Memory` 消费 `CreationFootprintRecorded.v1` Outbox 事件（`app/application/commands/creation_footprints.py`）：`Memory` 仅沉淀独立 `interest_signal`（不修改学业掌握度），`Evaluation` 投影晚间创作足迹。
- [x] 将 `api/v1/conversations.py` 中的直接 ORM 查询下沉至 `application/commands/conversations.py`，符合 DDD 分层约定。
- [x] 增量 Alembic 迁移 `20261128_45_conversation_context_ward.py` 已应用至 `.env` 对应 PostgreSQL 测试业务库 `duxue-test`，服务端全量 pytest 与 PostgreSQL 集成测试全绿。

## Gate 2 验收证据（2026-11-28）

- 业务测试库 `duxue-test` 由 `20261128_44` 升级至 `20261128_45 (head)`（新增可空 `conversation_threads.context_ward_id` 及索引）。
- 服务端全量 `pytest tests -q`：**1614 passed, 4 skipped, 3 subtests passed**（SQLite 套件 0 失败）；配合 `postgresql@14` PATH 复跑全部 6 组 PostgreSQL 集成测试：**11 passed**（合计 **1625 passed**）。
- 新增单元测试 `tests/unit/agent/test_edu_agent_registry_and_orchestrator.py`（6 passed）覆盖 5/11 注册校验、角色硬上限拒收、Default General Mode 写工具阻断与渐进加载、`context_ward_id` 越权 403 与只读零写入、`/v1/agent/*` SSE 与取消、以及 `CreationFootprintRecorded.v1` 幂等消费与兴趣信号隔离。
- 修改与新增 Python 文件 Ruff（`F,E9`）全绿。待用户 Gate 2 确认后归档并进入 Slice 2。
