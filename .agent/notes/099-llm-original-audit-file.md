# 模型原文与 stdout 摘要分开存放

`llm.response.validated` 仍只把长度和 SHA-256 打到 stdout / Grafana。完整模型原文写到 `duxue-server/var/agent-llm-audit.jsonl`，用同一条 `trace_id` 和摘要对齐。非生产环境默认写；生产必须同时打开 `AGENT_DEBUG_AUDIT_ENABLED` 并指定 `AGENT_DEBUG_AUDIT_PATH`。`AGENT_DEBUG_AUDIT_ENABLED=false` 全部关闭。文件只替换常见邮箱和手机号，不再截成 160 字。意图分类、计划整理、任务整理和 `agent_text` 都走 `record_model_response`。
