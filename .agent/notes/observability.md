# 可观测与评测运行

事实源：[observability](../../docs/observability.md) §7.1、[eval-offline](../../docs/technical/eval-offline.md)。

## 目标

三端用 OpenTelemetry 进 Grafana。Langfuse 只做可选的 AI observation，不增加 Alloy 或额外容器。离线评测按类型分目录、一例一个 JSON。语义是否达标留给人工复核。

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
- 评测按类型分目录。真实多轮不能拆成孤立 `problem/reply`。自动结构通过仍是 `pending_review`。退出码 0 不代表教学语义通过。
- Flutter 不持有 Grafana token，只带 `traceparent` 把白名单事件送到 `/telemetry/client-events`。relay 未配 Grafana 也先校验 payload，每主体 120 条/分钟。

## 注意

- 业务 `AgentTrace` / Checkpoint 在 PostgreSQL，不是 OTEL trace。
- Grafana MCP 配置含令牌，不能提交。
- 首次联网回放不能当成主生成已修好。
