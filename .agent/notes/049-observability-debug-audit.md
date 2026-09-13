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

## App relay 实施结果（2026-09-13）

- Flutter 绝不持有 Grafana token：只生成 W3C `traceparent` 并以当前短期 Bearer token 向 `/telemetry/client-events` 发送白名单信封。
- Server relay 在 exporter 禁用时也先验证 payload，避免“本地未配置 Grafana”意外变成接收任意儿童内容的通道；每个认证主体上限为 120 条/分钟。
- relay 采用独立 Resource `service.name=duxue-app` 导出 App 数据；接收 relay 请求本身仍属于 `duxue-server`，span 属性 `duxue.component=telemetry-relay` 用于区分。
- 本地 App 遥测使用 `duxue-app/config/dart-defines.local.example.json` 的可提交模板，并复制为 Git 忽略的 `dart-defines.local.json` 后通过 `--dart-define-from-file` 启动；模板只允许公开 URL、开关和采样率，禁止任何 OTLP/Grafana 凭据。

## 项目 MCP 配置（2026-09-13）

- Grafana MCP 的项目级配置位于 `.codex/config.toml`，由 `.cursor/mcp.json` 转换而来；配置文件因包含 Grafana 服务账号令牌而被 `.gitignore` 排除，不能提交。
- 在当前 Codex CLI 中，使用本项目配置可通过 `CODEX_HOME="$PWD/.codex" codex …`；例如 `CODEX_HOME="$PWD/.codex" codex mcp list` 可确认 `grafana` 已启用。不要把该令牌复制到 Flutter、服务端源码或其他受版本控制的文件中。
- 2026-09-13 的只读连通性测试确认 `mcp-grafana v1.4.1` 已能连接 Grafana Cloud，并发现三个 Loki 数据源；常规日志源 `grafanacloud-logs` 在最近一小时无可用标签，因此尚无可安全执行的项目日志 LogQL 查询。该结果说明 MCP/认证可用，不代表 OTLP 日志尚未开始写入。
