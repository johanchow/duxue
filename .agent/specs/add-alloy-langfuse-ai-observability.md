---
slug: add-alloy-langfuse-ai-observability
created: 2026-10-19T00:00:00Z
status: draft
---

# 轻量 Langfuse AI 可观测 spec

## 做什么 / 为什么

保持 Server 对 Grafana 的现有直连；Langfuse 作为可选的进程内第二个 OpenTelemetry span processor。它不增加本地或生产容器，只接收脱敏的 AI 模型调用元数据，不接收儿童对话、模型原文、图片或完整上下文。

## 验收标准

- [x] Compose 只保留既有 `api`、`worker`、`beat` 服务，不引入 Alloy 或 Langfuse 容器。
- [x] `LANGFUSE_ENABLED=false` 时本地和生产启动方式不变；启用且两把 key 齐全时才加载 Langfuse。
- [x] Grafana 继续接收 traces / metrics / logs；Langfuse 严格只导出 `llm.request`，且该 span 不含 prompt、completion、图片、输入事件或异常原文。
- [x] 模板、部署文档和 CI 不包含凭据或另一个环境文件；测试锁定开关和导出过滤边界。

## 实现计划（Gate 1：填完等人确认，不许自转）

1. 在既有 tracer provider 上可选初始化 Langfuse SDK，并把 `llm.request` 设为 deny-by-default 的唯一导出目标。
2. 加入 SDK 依赖与关闭默认值，移除 Alloy Compose、配置和部署流程。
3. 更新部署文档与观测文档，明确儿童数据边界、顶层 trace 取舍和 key 轮换要求。
4. 执行 Compose 配置、服务端测试与 diff 检查。

## 实现清单

- [x] 进程内 Langfuse processor 与严格 span allow-list
- [x] 无 Alloy 的 Compose / 部署流程 / 环境模板
- [x] 开关与数据边界单元测试
- [x] 完整验证、diff review；Gate 2 验收待用户确认

## 备注

- 为避免将 FastAPI 根 span 和其 Ward 输入送往 Langfuse，模型 generation 在 Langfuse 中显示为顶层 trace；这是有意的隐私优先取舍。
- Langfuse Dataset、人工标注、真实会话或图片导入、自动发布门槛仍需要独立的儿童数据治理规格；离线评测保持在本机 `evals/`。
- 验证：`ENV_FILE=.env.example docker compose config` 不含 Alloy；`pytest tests -q` 通过（552 passed）；
  `git diff --check` 通过。另以临时测试 key 初始化 Langfuse processor，未发送业务 span 或网络数据。
