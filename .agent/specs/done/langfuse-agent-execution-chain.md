---
slug: langfuse-agent-execution-chain
created: 2026-10-22T11:32:38Z
status: done
---

# Langfuse Agent 执行链路

## 做什么 / 为什么
Langfuse 当前只收到 `llm.request`，无法按对话查看完整执行，也看不到路由、Planning Graph 节点、答疑工具、候选校验、图检查与最终投影。补齐可关联、可审查的结构化链路，不外发孩子原话、模型正文、图片、SVG 或工具结果正文。

## 语义与边界

- `ConversationThread.id` 是孩子可见的连续对话，可跨 Tutoring / Planning / Reflection；Langfuse `session_id = thread_id`，在 Thread 创建/加载后、意图分类前设定，使路由模型也计入 Session。
- `AgentRun.id` 是目标 Agent 的一次任务生命周期；若路由判为 `continue`，多轮复用；handoff/start 建新 Run。把 `run_id` 写到安全的 workflow / node / tool / check observation 及请求 trace 的关联元数据，以便按 Run 筛选；不能用它代替已开始的路由调用的 session 属性。
- 每次 `/companion/turn` 是独立 trace；同一 Thread 下的多次请求进入同一 Langfuse Session，包括尚未创建 Run 的意图路由和无 Run 的 clarify/safety。一次 Run 跨多条 trace，用 `run_id` 聚合观察。
- Langfuse 仅上报安全的结构字段：节点/工具名称的封闭枚举、状态、结果类别、时延、组件版本、token 与必要的随机 ID。允许导出前须审查该 span 的 attributes、events、status 和异常记录；不开放 FastAPI/SQLAlchemy/HTTPX/Redis/Celery 自动 span。`agent.thread_id` 和 `agent.run_id` 可作交叉查询，不能替代 Langfuse 专用 session 属性。
- 本地 Grafana/Loki 的既有诊断能力继续保留，但导出到 Langfuse 的 observation 不得包含 `input.text`、`shown`、`reason` 自由文本、prompt、completion、图片、SVG、工具 args/result、SQL/HTTP 内容或异常原文。

## 验收标准
- [x] 两轮续接同一 Tutoring Run 时，Langfuse 有同一 `session_id=thread_id` 的两条 turn trace，且 `run_id` 相同；第三轮 handoff 到 Planning 后 `session_id` 仍相同、`run_id` 变化。路由模型及无 Run 的 clarify/safety 均在 Thread Session 中，无 Run 的轮次不生成虚假 `run_id`。
- [x] 单轮 trace 能看到安全的入口/路由、workflow、Planning Graph 具体节点或 Tutoring 阶段、每次模型 generation、真实工具调用、候选结构检查、答案/图安全检查、重试与最终结果。可区别“没有调用工具”“预置 widget_guidelines”“实际调用 widget_guidelines”。
- [x] 并发文字与图判官的 generation 正确挂在同一轮 trace 下；失败、兜底、超预算和图丢弃可从结构化状态判断。
- [x] 导出采用经审查的显式安全 span 集，不外发自动基础设施 span 或儿童/模型/图像/工具正文；对 attributes、events、status、异常记录做测试。
- [x] 原有 Grafana 链路与 `LANGFUSE_ENABLED=false` 行为不回退；相关服务端测试全绿，文档与决策笔记同步。
- [x] 共享 OpenTelemetry 采样器不会遗漏 Langfuse Session 轮次：环境模板用全量采样，并记录生产未提交环境需同步的参数。

## 实现计划（Gate 1：填完等人确认，不许自转）
1. 在 `duxue-server/app/infrastructure/observability/telemetry.py` 增加安全的 turn / route / workflow / node / tool / check span API；将 Langfuse 过滤器从仅 `llm.request` 扩展为这些显式标记的 span，并保证未知 span 默认拒绝。明确 Langfuse Session 属性及最小关联 ID。
2. 在 `companion_coordinator.py` 于取得 Thread 后、意图分类前建立请求级安全根节点并传播 `session_id=thread_id`；Run 确定后追加 `run_id` 关联属性。覆盖 continue、handoff、clarify、安全拒绝和幂等返回。避免把现有孩子原话事件附在可导出的根节点。
3. 在 `planning_workflow.py` / `planning_adapter.py` 埋 Planning Graph 节点和关键检查；在 `tutor_loop.py` / `tutor_tools.py` / `tutoring_workflow.py` 埋实际工具、候选检查、文字/图判官、重试、配图校验与投影结果。只记录封闭的结果类别，不记录语义原文。为线程池并行判官显式传播 trace context。
4. 更新 `docs/observability.md`、部署说明与环境模板，说明共享采样器；完成实现后写 `.agent/notes/` 决策记录。

影响文件：上述服务端文件；`duxue-server/tests/unit/test_observability.py`、`tests/unit/test_alloy_observability_config.py`、Companion/Planning/Tutoring 对应测试；必要时更新 `.env.example` 的注释。

测试计划：先用失败测试锁定意图分类也具有 Thread Session 属性、Run 的续接/切换、span 父子关系、工具与检查节点、并发判官上下文及导出隐私边界；小步实现并跑相关测试、完整 `pytest tests -q`、`git diff --check` 和最终 diff review。测试不发送真实 Langfuse 网络请求。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 会话语义与安全 trace 根节点
- [x] 路由、Planning、Tutoring、工具与检查 span
- [x] 并发判官上下文传播
- [x] 自动化测试与隐私边界验证
- [x] 文档、决策笔记、完整测试和 diff review

## 备注

- 既有 `.agent/specs/add-alloy-langfuse-ai-observability.md` 记录原先“仅模型调用”的边界；本 spec 对 Agent 链路作明确扩展，不更改原部署方式。
- 曾考虑 `session_id=run_id`，但意图分类发生在 Run 选定前，会漏掉路由 generation 的 Session 级统计；以 Thread 作为 Session 并将 Run 作为执行分组字段可完整覆盖入口与 handoff。
- 验证：`duxue-server/.venv/bin/pytest tests -q` 通过（586 passed）；新增 InMemorySpanExporter 测试不发网络请求；`ruff check --select I,UP035,RUF100` 和 `git diff --check` 通过。Gate 2 用户已确认，按请求归档并提交。
