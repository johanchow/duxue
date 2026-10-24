# Langfuse 对话正文上报

日期：2026-10-24。对应 spec：`.agent/specs/done/langfuse-conversation-payloads.md`。

- 现象：同一 Session 的 Agent、generation、check 等 observation 已存在，但全部 `input/output=null`，Langfuse 回放显示 `No messages or tools`。此前这是明确的正文排除策略，不是 session 关联或 observation 类型错误。
- 用户调整数据策略，授权上报孩子问话、模型回复、工具正文。新轮次在根 `agent.turn` 写入孩子可见输入和最终展示回复；模型 generation 写入实际消息和原始回复；实际工具与预置指南写入参数/结果。
- 用户追加要求保留孩子图片供 MCP 分析。OSS 签名 URL 有效期有限；Langfuse 5 的 OTEL exporter 会从 `langfuse.observation.input` 中的 `data:` URL 提取并上传 Media，trace 保留 Media 引用。根轮次也要包含图片，以便 Session 回放。共享的 Grafana OTLP exporter 单独将图片字节替换为占位符，避免大 span。
- Langfuse 与 Grafana 共用同一 OpenTelemetry provider；在 span 上添加正文属性会同时进入 Grafana trace。旧 trace 不会回填。
- 关键接点：模型正文必须在 `model_call_span` 活跃时写入；最终回复取 `_visible_outcome_content` 并在成功提交后记录，不使用模型原始候选，否则回放可能显示被安全检查拒绝的内容。
- 后续发现仅有模型原文和根轮次展示文案仍无法直接证明 `next_subgoal` 的实际写回。`tutoring.apply_problem` 现在记录采纳候选与规则处理后的目标；Loki 的 `tutor.subgoal.committed` 只在 Coordinator 的数据库提交成功后写入，`agent.turn.output` 同时记录最终展示正文。两条日志以 trace/run/thread ID 关联，避免把一次被拒候选误认作写回值。
