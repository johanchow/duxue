# 可观测性与 Agent 调试审计

> 日期：2026-09-12  
> 范围：当前仓库只读审计；未修改业务实现。

## 结论

- `docs/observability.md` 定义了 OTEL + Grafana LGTM 的目标架构，但当前尚未接入：三端没有 SDK 初始化或自动插桩代码；`duxue-server/.env` 与 `.env.prod` 均未配置任何 `OTEL_*` 项；Compose/Docker 启动命令也未通过 `opentelemetry-instrument` 启动。
- 服务端只在 `requirements.txt` 声明 OTEL/structlog 依赖，未配置 exporter、日志桥、资源属性或业务 metrics；仓库中无 Grafana/Alloy/Loki/Tempo/Prometheus 配置、看板或告警规则。
- Agent 的 `AgentTrace`、`AgentStreamEvent` 和 `AgentCheckpoint` 是 PostgreSQL 内的业务审计/重放数据，不是 OTEL trace，也不会出现在 Grafana。设计上只保留脱敏 `ContextEnvelope.trace_snapshot()`；原始用户输入和模型原始回复均未保存或打印。
- Agent 模型网关将模型调用异常归类为 `model_transport_error` / `invalid_model_candidate`，上游再降级，但未输出错误类型、耗时、模型名、token 用量或请求关联 ID；模型原始输出同样不可排查。

## 调试期建议

调试内容不应直接进入普通 Loki 日志。为儿童数据建立独立、加密、短留存、严格 RBAC 的 `agent_debug_audit` 通道，并默认脱敏/截断：记录 input/output 的 hash、长度、结构摘要；仅以显式开关在受控环境记录原文。所有记录须带 `trace_id`、`run_id`、`thread_id`、`agent_type`、`model`、结果分类和时延，禁止记录 API Key、Authorization、图像 data URL、完整 context 或思维链。

## 接入优先级

1. 服务端先接 OTLP trace/log/metric 导出，并在 API、Celery、SQLAlchemy、Redis、HTTPX/OpenAI 调用上做实际插桩。
2. 在统一的模型网关为每一次 LLM/VLM 调用建 span，记录安全属性、用量、provider request ID、错误分类与降级原因；补 Agent run/route/workflow span。
3. 补成本、推理延迟、错误、fallback、队列、帧上传与设备心跳等指标及 Grafana 告警。
4. 再接 Flutter `traceparent` 注入与 Android OkHttp/上传 span；移动端保留本地错误与队列遥测。

## 实施结果（2026-09-12）

- 已完成服务端 Phase 1：标准 OTLP bootstrap、FastAPI/SQLAlchemy/Celery/Redis/HTTPX 插桩、Agent/LLM/VLM/Celery/采集指标，以及 Grafana dashboard 与告警模板。
- 测试进程必须在导入 `app.main` 前设置 `OTEL_SDK_DISABLED=true`，否则本机 `.env` 的真实 Grafana endpoint 会让 pytest 启动 exporter 线程并产生不必要外网请求。
- OTLP HTTP exporter 的 smoke test 已确认能根据标准环境变量构造 `/v1/traces` 与 `/v1/metrics` 请求；受 sandbox 网络限制，无法在此环境验证真实 Grafana Cloud 接收。
