# Langfuse Agent 执行链路

日期：2026-10-22。对应 spec：`.agent/specs/done/langfuse-agent-execution-chain.md`。

- `session_id=ConversationThread.id`。路由模型在 Run 选定前执行，用 `run_id` 作 Session 会漏掉它的 Session 级统计。`AgentRun.id` 写为 trace / observation metadata，供单次 Agent 执行筛选；handoff 后 Thread 不变、Run 变化。
- Langfuse 只允许 `duxue.agent` 与 `duxue.model` 的显式业务 span。保留 Grafana 的自动基础设施追踪；不扩大到 HTTP、SQL、Redis 或异常正文。
- 导出 span 的事件仅保留受控类别和长度。已有 `agent.turn.received` 事件中的儿童原话仍保留在不导出 Langfuse 的 HTTP 父 span 与原审计日志，不进入 Langfuse span。所有可导出 context manager 关闭自动异常记录，避免 Python 异常 message 携带原文。
- 答疑模型工具请求和预置 `widget_guidelines` 分别记录 `model_request` / `preloaded`；未知工具只记 `unknown_tool`。并发文字/图判官以 `copy_context()` 继承当前 trace 与 Session。
- Langfuse 的 trace 是单轮请求，Session 是连续对话，Run 是 Agent 任务；调试某个 Run 时按 `run_id` metadata 筛选，不把三个生命周期混成一个 ID。
- Grafana 与 Langfuse 共用采样器。为了能看到完整的 Session，把环境模板的 `OTEL_TRACES_SAMPLER_ARG` 从 0.2 调整为 1.0；生产环境的未提交配置还需单独同步。
