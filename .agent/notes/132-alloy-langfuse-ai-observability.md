# 进程内 Langfuse AI 可观测性

日期：2026-10-19

- 决策：不把 Alloy 设为默认依赖。Server 继续直连 Grafana；Langfuse Cloud 是可选的、同一 Python
  `TracerProvider` 上的第二个 span processor，不增加容器、端口或 Compose override。
- Langfuse 仅接收 `llm.request`，不接收 logs / metrics。严格 allow-list 的生成 span 只保留
  component/version、模型、token、时延和结果类别；儿童输入、模型原文、图片、ContextEnvelope、认证、
  API key 与异常原文不导出。
- 为让现有 span 被 Langfuse 正确渲染为 generation，`model_call_span` 仅添加
  `langfuse.observation.type=generation`、模型名和安全的 usage JSON；没有添加 prompt / completion。
- `LANGFUSE_ENABLED=false` 为默认值。只有明确批准 Cloud 外发时，才在部署主机未提交的 `.env.prod`
  配置 `LANGFUSE_ENABLED=true` 和项目 API keys；本地无需配置也不会发出 Langfuse 请求。
- Langfuse 的 Dataset、人工标注、真实会话/图片导入、自动发布门槛不属于本改动；必须先有儿童数据
  留存、删除、RBAC、人工复核和明确授权的独立规格。离线评测仍在本机 `evals/` 中运行。
