# Langfuse 对话正文上报

日期：2026-10-24。对应 spec：`.agent/specs/done/langfuse-conversation-payloads.md`。

- 现象：同一 Session 的 Agent、generation、check 等 observation 已存在，但全部 `input/output=null`，Langfuse 回放显示 `No messages or tools`。此前这是明确的正文排除策略，不是 session 关联或 observation 类型错误。
- 用户调整数据策略，授权上报孩子问话、模型回复、工具正文。新轮次在根 `agent.turn` 写入孩子可见输入和最终展示回复；模型 generation 写入实际消息和原始回复；实际工具与预置指南写入参数/结果。图片 data URL 只写 `[image omitted]`。
- Langfuse 与 Grafana 共用同一 OpenTelemetry provider；在 span 上添加正文属性会同时进入 Grafana trace。旧 trace 不会回填。
- 关键接点：模型正文必须在 `model_call_span` 活跃时写入；最终回复取持久化前的 `_visible_outcome_content`，不是模型原始候选，否则回放可能显示被安全检查拒绝的内容。
