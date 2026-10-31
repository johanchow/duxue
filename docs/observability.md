# 读学系统 — 可观测性方案设计

> 版本 v1.0 | 覆盖：duxue-server · duxue-cam · duxue-app
>
> 全系统架构见：[docs/technical/ARCHITECTURE.md](./technical/ARCHITECTURE.md)

> 实施状态（2026-09-12）：服务端已接入标准 OTLP traces / metrics、FastAPI / SQLAlchemy / Celery / Redis / HTTPX 自动插桩，以及 Agent、LLM/VLM、采集与 Celery 的手工业务遥测。部署、dashboard 与告警模板见 [`ops/observability/`](../ops/observability/)。Flutter 与 Android 的 trace context 接入仍待单独实施。

> 实施状态（2026-09-13）：Flutter App 已经通过已认证的 Server relay 上报安全的体验 telemetry；`service.name=duxue-app` 与 `service.name=duxue-server` 在 Grafana 中保持独立，且可由 W3C `trace_id` 串联。Android Cam 仍待接入。
>
> 实施状态（2026-10-20）：Server 继续直连 Grafana。可选 Langfuse Cloud 以服务端进程内的第二个
> OTEL span processor 实现，默认关闭；只接收字段白名单后的 AI trace，不接收 logs、metrics、儿童
> 原文、模型原文、图片或完整上下文。部署说明见
> [`ops/observability/README.md`](../ops/observability/README.md)。

> 实施状态（2026-10-22）：Langfuse 的安全导出范围扩展到 Companion turn / route / workflow、
> Planning 与 Tutoring 节点、只读工具、结构与安全检查、模型 generation。每次 `/companion/turn`
> 是一条 trace；`ConversationThread.id` 作为 Langfuse `session_id`，从意图分类前开始传播；
> `AgentRun.id` 作为可筛选的执行关联字段。一次对话中切换 Agent 会更换 Run，但保留 Session。
> 导出仍为显式白名单，并限制在 `duxue.agent` / `duxue.model` instrumentation scope；
> 不包含 HTTP、SQL、Redis 等自动 span，也不包含儿童原话、模型正文、图片、SVG、工具参数或结果正文。
> `widget_guidelines` 若预置给模型会标记为 `preloaded`，实际工具请求标记为 `model_request`。

> 实施状态（2026-10-24）：按产品数据收集策略，Langfuse 的 Companion 根 observation 记录孩子本轮可见输入、上传图片和最终展示回复；模型 generation 记录实际消息、所见图片与原始回复；工具 observation 记录参数和结果。Langfuse SDK 从 `data:` URL 上传图片为 Media 并在 trace 留下引用，便于后续 MCP 分析。共享的 Grafana OTLP trace exporter 仍接收文字字段，但图片字节在该出口替换为 `[image omitted]`；旧 trace 不会自动补齐。

---

## 一、背景与目标

读学系统由三端协作完成核心业务流：

```
guardian 在 App 查看报告
    ↑
duxue-server 批量 AI 分析 + 报告聚合
    ↑ REST API（帧元数据 / 心跳）
duxue-cam 定时抓拍上传（Android 长驻 Foreground Service）
```

三端之间存在跨进程、跨网络的依赖，单端日志无法定位跨端问题。可观测性目标：

| 目标 | 说明 |
|------|------|
| **端到端链路串联** | 一个用户请求从 App → Server → Celery Worker 全程可追踪 |
| **采集健康感知** | 掌握设备心跳中断、帧上传失败、本地队列积压等关键事件 |
| **成本可见** | 每日实际推理帧数、Batch 降级率——第一期不做帧过滤，这两项直接反映账单 |
| **AI 推理性能** | 监控 VLM 推理延迟、Celery 队列积压，防止分析任务堆积 |
| **三端统一入口** | 日志、链路、指标汇聚到同一个 Dashboard，减少工具切换 |

---

## 二、方案对比

### 2.1 候选方案

| 方案 | 工具组合 | 优势 | 劣势 |
|------|---------|------|------|
| **A. 纯 OpenTelemetry + Grafana** | OTEL SDK × 3 端 → Grafana OTLP → Loki / Tempo / Prometheus → Grafana | 三端统一标准；Traces/Logs/Metrics 在 Grafana 内互相跳转；无厂商锁定 | 移动端 OTEL SDK 较新，Logs 信号在 Android/Flutter 侧为实验阶段 |
| **B. Sentry + Prometheus/Grafana** | Sentry SDK × 3 端（错误）+ OTEL/Prometheus（指标） | Crash 报告体验最好；移动端接入最简单 | 两套工具，日志与链路不在同一平台；Sentry 免费额度有限 |
| **C. Firebase Crashlytics + 自定义** | Firebase × 移动端 + 自研埋点 | Google 生态，Android/Flutter 接入极简 | 仅覆盖移动端崩溃，无链路追踪，Server 端需另建体系 |

### 2.2 选型结论

**采用方案 A（纯 OpenTelemetry + Grafana LGTM 栈）**，理由：

1. **三端有标准 SDK**：Python / Android / Flutter 均有官方或官方维护的 OTEL SDK
2. **链路天然跨端**：W3C `traceparent` Header 让 App → Server → Worker 的 span 串在同一 trace_id 下，无需额外 hack
3. **Grafana 三信号联动**：同一界面可以从 Metrics 曲线异常点跳到 Trace，再从 Trace 的 span 跳到对应日志行
4. **可自托管**：数据不出服务器，满足系统的隐私定位

移动端 Logs 信号尚不成熟的问题，用"**在日志中手动注入 trace_id**"绕过——日志不走 OTEL Log SDK，但每条日志携带当前 span 的 trace_id，在 Grafana Loki 里仍可通过 trace_id 关联。

---

## 三、整体数据流

```
┌─────────────────────────────────────────────────────────────┐
│                        三端 SDK                              │
│                                                             │
│  duxue-app (Flutter)    duxue-cam (Android)                 │
│  opentelemetry-dart     opentelemetry-android               │
│  ── Traces ──────────── Traces ────────────                 │
│  ── Logs (手动 trace_id) Logs (手动 trace_id)                │
│                    │                   │                    │
│  duxue-server (Python)                 │                    │
│  opentelemetry-sdk                     │                    │
│  ── Traces / Metrics / Logs ───────────┘                   │
└────────────────────────┬────────────────────────────────────┘
                         │ OTLP（HTTPS）
                         ▼
               ┌─────────────────┐
               │ Grafana OTLP    │  统一收集 & 路由
               │ Gateway / LGTM  │
               └────┬──────┬─────┘
                    │      │      │
              Traces│  Logs│  Metrics
                    ▼      ▼      ▼
               Tempo    Loki   Mimir/Prometheus
               (链路)   (日志)  (指标)
                    └──────┴──────┘
                           │
                      Grafana UI
                   （统一 Dashboard）
```

### 3.1 跨端链路串联原理

App 或 Cam 发起 HTTP 请求时，OTEL SDK 自动在请求头注入：

```
traceparent: 00-{trace_id}-{span_id}-01
```

Server 端的 FastAPI 自动插桩读取此 Header，将服务端 span 挂载到同一 `trace_id`。Celery 任务通过消息 metadata 继续传播 context。最终一次完整的"截帧 → 推理 → 报告"链路在 Tempo 中表现为：

```
App 查询报告请求 (1ms)
  └─ FastAPI GET /reports/{id} (45ms)
       ├─ SQLAlchemy SELECT reports (12ms)
       └─ [异步] Celery generate_report (3200ms)
            ├─ VLM 推理 (2800ms)
            └─ SQLAlchemy INSERT behavior_segments (80ms)
```

---

## 四、各端关键实现点

### 4.1 duxue-server（FastAPI + Celery）

**自动插桩覆盖范围：**

| 组件 | 插桩库 | 自动捕获内容 |
|------|--------|------------|
| FastAPI | `opentelemetry-instrumentation-fastapi` | 每个路由的请求/响应、HTTP 状态码 |
| SQLAlchemy | `opentelemetry-instrumentation-sqlalchemy` | 每条 SQL 语句及耗时 |
| Celery | `opentelemetry-instrumentation-celery` | 任务入队、执行、成功/失败 |
| Redis | `opentelemetry-instrumentation-redis` | 每次 GET/SET/LPUSH 操作 |

**日志与 Trace 关联：**

Python 端使用 OTEL Log Bridge，structlog 日志经 OTLP 导出到 Loki，每条日志自动携带当前 `trace_id` 和 `span_id`，无需手动注入。

**自定义业务指标（需手动埋点）：**

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `duxue.ai.inference_duration_seconds` | Histogram | VLM 推理耗时分布 |
| `duxue.celery.queue_depth` | Gauge | Celery 队列待处理任务数 |
| `duxue.capture.frames_total` | Counter | 接收帧总数（含成功/失败标签） |
| `duxue.device.online_count` | Gauge | 当前在线设备数（按心跳判定） |
| `duxue.vlm.frames_analyzed_daily` | Counter | **每日实际推理帧数。**第一期不做帧过滤，这个数字直接等于账单，也是判断何时该推进自部署的依据 |
| `duxue.batch.fallback_ratio` | Gauge | **降级到实时 API 的批次占比。**长期偏高说明 Batch 实际时延不可靠，需重新评估该方案 |

> 后两个是**成本指标**，优先级不低于性能指标——它们失效时系统功能完全正常，只是账单翻几倍，没有指标就发现不了。

### 4.2 duxue-cam（Android / Kotlin）

Cam App 的可观测性核心是**采集与上传链路的健康度**。OTEL SDK 负责 HTTP 调用链路，本地状态通过手动埋点记录：

| 关键事件 | 上报方式 | 说明 |
|---------|---------|------|
| 设备绑定（`/devices/bind`） | HTTP 自动插桩 | Retrofit + OkHttp 自动产生 span |
| 单帧上传 | HTTP 自动插桩 | 覆盖申请预签名 URL → PUT OSS → 提交元数据三段 |
| 上传失败与重试 | Span Event | 记录失败原因（网络 / 预签名过期 / 服务端 5xx）与重试次数 |
| 本地队列积压数 | Gauge（随心跳上报） | **最重要的单项指标**：积压持续增长是网络或服务端问题的最早信号 |
| 抓拍失败 | Span + 错误标记 | CameraX 异常（摄像头被占用等） |
| 服务被系统回收 | 手动事件 | 用于评估各厂商机型的保活成功率 |

> 队列积压数建议随心跳一并上报到服务端，而非只靠 OTEL——移动端 OTEL 在应用被杀时可能来不及导出，而心跳是必发请求。

日志：在每条 Timber 日志中手动注入当前 span 的 `trace_id`，通过 Loki 的 derived field 配置实现日志→链路跳转。

### 4.3 duxue-app（Flutter / Dart）

App 端所有 HTTP 请求通过 dio Interceptor 统一注入 `traceparent` Header，不需要在每个业务代码处埋点。

| 关键场景 | 处理方式 |
|---------|---------|
| 查询报告 | dio 自动产生 span + 注入 header |
| 生成邀请码 | 同上 |
| 设备状态轮询 | 同上 |
| 页面导航 | 可选：为每个路由创建 span（低优先级） |

---

## 五、Grafana 看板规划

### 5.1 推荐 Dashboard 分层

| Dashboard | 受众 | 核心面板 |
|-----------|------|---------|
| **系统健康总览** | 运维/开发 | API 请求成功率、Celery 队列深度、在线设备数、错误率趋势 |
| **AI 推理性能** | 开发 | VLM 推理 P50/P95/P99、任务队列等待时长、批次完成时长分布 |
| **成本监控** | 开发/运营 | 每日实际 VLM 调用帧数、Batch 降级率、单 ward 日均成本趋势 |
| **采集监控** | 运维 | 在线设备数、帧上传成功率、各设备本地队列积压趋势、心跳掉线事件时间线 |
| **链路追踪（Tempo）** | 开发排障 | 按 trace_id / ward_id / service 过滤，查端到端链路 |

### 5.2 三信号联动路径

```
Metrics 看板发现异常（如 AI 推理 P95 突增）
    │ 点击时间段
    ▼
Tempo 查该时段慢 Trace 列表
    │ 点击某条 trace
    ▼
查看完整 span 树（App → API → Celery → VLM）
    │ 点击某个 span
    ▼
Loki 过滤该 trace_id 的所有日志行
```

---

## 六、部署拓扑

### 6.1 推荐：Grafana Cloud 免费套餐

**无需运维任何基础设施，注册即用。** 这与整个读学系统"让开发简单"的原则一致——可观测性后端不应成为运维负担。

注册地址：[grafana.com/products/cloud](https://grafana.com/products/cloud/)，选择 Free 套餐，免费额度对早期阶段完全够用：

| 信号 | 免费额度 | 读学系统预估用量 |
|------|---------|----------------|
| Traces | 50 GB/月 | < 1 GB（低频 API） |
| Logs | 50 GB/月 | < 2 GB |
| Metrics | 10,000 series | < 50 series |

注册后，Grafana Cloud 控制台会直接提供三个值：

| 配置项 | 说明 | 示例格式 |
|--------|------|---------|
| `OTLP_ENDPOINT` | 三端统一上报地址 | `https://otlp-gateway-prod-xx.grafana.net/otlp` |
| `GRAFANA_INSTANCE_ID` | 实例 ID，用作 Basic Auth 用户名 | `123456` |
| `GRAFANA_API_TOKEN` | API Token，用作 Basic Auth 密码 | `glc_xxx...` |

### 6.2 备选：自托管（数据不出服务器）

如果隐私合规要求数据不离开私有服务器，在读学服务器上用 Docker Compose 部署 LGTM 栈：

```
Grafana Alloy   ← 三端 OTLP 统一入口（4317/4318 端口）
Grafana Loki    ← 日志存储
Grafana Tempo   ← Trace 存储
Prometheus      ← 指标存储
Grafana         ← 统一 UI（3000 端口）
```

资源估算（早期阶段）：总计约 2GB 内存、8GB/月 磁盘增量。与读学服务本身部署在同一台机器时需评估资源余量。

---

## 七、配置参数说明

三端的 OTEL 配置高度对称，统一通过环境变量或初始化参数注入，**不硬编码在代码里**。

### 7.1 duxue-server（环境变量）

Server 端 OTEL SDK 完整支持通过环境变量配置，无需改动代码：

| 环境变量 | 值 | 说明 |
|---------|-----|------|
| `OTEL_SERVICE_NAME` | `duxue-server` | 在 Grafana 中标识服务名 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `https://otlp-gateway-prod-xx.grafana.net/otlp` | OTLP 上报地址 |
| `OTEL_EXPORTER_OTLP_HEADERS` | `Authorization=Basic <base64(instanceId:token)>` | Grafana Cloud 鉴权 |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Grafana Cloud 推荐协议 |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | 基于父 span 的比例采样 |
| `OTEL_TRACES_SAMPLER_ARG` | `0.2` | 采样率 20%（生产可调低） |
| `OTEL_LOG_LEVEL` | `info` | SDK 自身日志级别 |

在 `.env` 文件中统一维护，通过 `python-dotenv` 或 Docker Compose `env_file` 加载。

服务端不再需要用 `opentelemetry-instrument` 包裹启动命令：应用 bootstrap 会在检测到 `OTEL_EXPORTER_OTLP_ENDPOINT` 后初始化 exporter。测试或离线环境设置 `OTEL_SDK_DISABLED=true`；未配置 endpoint 时不会创建 exporter。`api`、`worker`、`beat` 通过 `OTEL_SERVICE_COMPONENT` 作为资源属性区分。

### 7.1.1 可选 Langfuse（无额外进程）

Langfuse 默认关闭。需要 AI trace 时，在同一份服务端环境文件配置 `LANGFUSE_ENABLED=true`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY` 与区域对应的 `LANGFUSE_BASE_URL`。它作为同一 Python 进程中的第二个 OpenTelemetry span processor 工作；Grafana 仍使用已有的 OTLP exporter，因此不需要 Alloy、Compose override 或额外容器。

Langfuse 导出采用显式 span allow-list：只接收 `duxue.agent` 创建的 turn、route、workflow、node、tool、check span，以及 `duxue.model` 创建的 `llm.request` generation。HTTP、SQL、Redis、Celery 等自动 span 不进入 Langfuse。每条导出的 observation 都有 metadata `kind`、`kind_id`、`kind_version`，用来回到 Workflow、Agent、Gate、Tool 或代码步骤；字段含义见 [Agent 配置设计](technical/design-agent.md) 第五节。Thread ID 从意图分类前传播为 `session_id`；Run ID 是可筛选的执行关联字段。根轮次有 Ward 输入、上传图片和展示回复；模型 generation 有实际消息、图片与原始回复；工具有参数与结果。Langfuse SDK 将图片数据提取为 Media 引用，异常原文与认证/API key 不主动采集。

路由 observation 记录本轮输入和路由决定；workflow 记录授权调用和返回的 Outcome；node 记录节点参数与结果（数据库 Session、模型客户端等对象只记类型）；check 记录实际检查输入与通过、拒绝或跳过的结果。节点已有专用业务投影时优先保留它，例如 `tutoring.apply_problem` 的目标写回。执行异常只记类型，不把异常消息写进 observation。新增字段仅对部署后的新 trace 生效。

Grafana 与 Langfuse 共用同一个 OpenTelemetry `TracerProvider` 和采样器。若要在 Langfuse 查看每一轮完整 Session，部署环境需设 `OTEL_TRACES_SAMPLER_ARG=1.0`；小于 1 的值会让部分整轮 trace 在两处都缺席。环境模板默认全量采样，生产主机未提交的 `.env.prod` 需单独核对。

### 7.1.2 Agent 数据边界

Grafana 的 HTTP 父 span、OTLP log / stdout JSON 日志包含运行关联 ID、模型、结果、时延、token 用量（供应商返回时）、**Ward 本轮问话文本**（`input.text`，上限 2000 字，邮箱与大陆手机号已遮蔽）以及输入/输出的长度和 SHA-256 摘要。共享 OTLP tracer 上的 Companion、模型与工具 span 还包含 `langfuse.observation.input/output` 原文，因此 Grafana trace 同样可读这些文字正文；其专用 exporter 将图片 data URL 替换为占位符。HTTP 父 span 不导出到 Langfuse。答疑轮另有 `tutor.turn.result` 类别事件（`act`、`relation`、结果 `shown|fallback|blocked`、配图丢弃类别、形状告警）。Authorization 和 API Key 不主动写入 trace。

答疑的每一次生成与审核按 `tutoring.attempt` 节点分组（`primary`、`repair`、`backup`，以及配图重画）；模型 generation 记录实际发送的消息、原始回复、模型与 `ai.prompt_id`，即使候选后来被拒也保留。`tutoring.candidate_schema` 记录原始候选和结构校验结果；`tutoring.exit_gate` 记录候选、当时的 `permit`、题目摘要以及最终拒绝类别；文字和图的独立审核节点记录实际审核输入与结构化结论，文字泄露原因在 `tutor.leak.reason`。最终 `tutoring.output_safety` 也记录待检查文字和结果。根 `agent.turn` 的 output 才是孩子最终看到的回复。回放时先按 attempt 分组，再比较原始候选、每层审核和最终展示，不能把被拒草稿误当成已展示内容。旧 trace 无法回填；2026-10-24 18:25 的失败轮早于 19:08 的正文采集版本生产启动，只有长度和 SHA-256，不能还原三版原文。

答疑题目推进时，`tutoring.apply_problem` observation 的 input 记录 `previous_subgoal` 与本轮采纳候选的 `candidate_next_subgoal`，output 记录规则处理后的 `active_subgoal` 和是否变化。只有数据库提交成功后才写 Loki `tutor.subgoal.committed` 日志（含这些值及 problem/turn/run/thread ID）；同一轮的 `agent.turn.output` 日志记录最终展示文案 `shown`。按 `trace_id` 可直接对照模型原始回复、采纳候选、写回目标与孩子看到的文字；失败回滚不会产生 `committed` 日志。

模型原文除 Langfuse/Grafana trace 外仍可写在独立审计文件，不进 stdout、普通应用日志或 Loki。非生产环境默认写入 `duxue-server/var/agent-llm-audit.jsonl`；生产环境只有同时设置 `AGENT_DEBUG_AUDIT_ENABLED=true` 和 `AGENT_DEBUG_AUDIT_PATH` 才写入。`AGENT_DEBUG_AUDIT_ENABLED=false` 在任何环境都关闭。每一行带与 stdout 相同的 `trace_id`、`span_id`，`kind` 区分三类记录：`input`（Ward 问话，元数据含 run/thread id）、`output`（模型原文，含操作名、长度和 SHA-256）、`turn_result`（孩子最终看到的文本，元数据为 act、relation、结果、失败原因、配图丢弃原因）。按 `trace_id` 可连接完整一轮。

### 7.2 duxue-cam（Android Build Config）

Android 端配置通过 `BuildConfig` 字段注入，在 `build.gradle.kts` 的 `buildConfigField` 中区分 debug / release 环境：

| 配置项 | debug 值 | release 值 | 说明 |
|--------|---------|-----------|------|
| `OTEL_SERVICE_NAME` | `duxue-cam-debug` | `duxue-cam` | 区分环境 |
| `OTEL_ENDPOINT` | `http://10.0.2.2:4318`（模拟器） | Grafana Cloud URL | OTLP HTTP 地址 |
| `OTEL_AUTH_HEADER` | 空（本地无鉴权） | `Basic <base64>` | 生产环境鉴权 |
| `OTEL_SAMPLE_RATE` | `1.0` | `0.2` | debug 全量采样 |

> `OTEL_AUTH_HEADER` 等敏感值不能提交到 Git，通过 CI/CD 的 Secret 注入到 `local.properties` 或环境变量，再由 Gradle 读取写入 `BuildConfig`。

### 7.3 duxue-app（Flutter 环境变量 / dart-define）

Flutter 通过 `--dart-define` 在构建时注入配置，运行时通过 `String.fromEnvironment` 读取：

| dart-define Key | debug 值 | release 值 | 说明 |
|----------------|---------|-----------|------|
| `API_BASE_URL` | 本机 Server URL | App 的公开 API URL | API 与 relay 的基础地址 |
| `APP_TELEMETRY_ENABLED` | `true` | `true` | 未设置时为 `false`，完全 no-op |
| `APP_TELEMETRY_RELAY_URL` | 本机 relay URL | 生产 relay URL | 默认为空时即使开关开启也不发送，防止误投递 |
| `OTEL_TRACE_SAMPLE_RATE` | `1.0` | `0.2` | App trace 的采样率；Metric / Event 不采样 |

本地调试可以复制 `duxue-app/config/dart-defines.local.example.json` 为被 Git
忽略的 `dart-defines.local.json`，再使用：

```bash
flutter run --dart-define-from-file=config/dart-defines.local.json
```

当前实现不使用 `OTEL_AUTH_HEADER`：Grafana Cloud 的长期 token 绝不可出现在 APK / IPA。App 只接受上述非敏感 dart-define，并使用现有短期 Bearer 登录态调用 Server relay。生产构建由 CI/CD 逐项注入这些公开配置：

```bash
flutter build apk \
  --dart-define=API_BASE_URL=https://duxuelai.xyz/api \
  --dart-define=APP_TELEMETRY_ENABLED=true \
  --dart-define=APP_TELEMETRY_RELAY_URL=https://duxuelai.xyz/api/telemetry/client-events \
  --dart-define=OTEL_TRACE_SAMPLE_RATE=0.2
```

relay 对每个认证主体限流 120 条/分钟、只接受严格的 name / attribute 白名单，并用独立 OTLP Resource 转发。因此转发数据的 `service.name=duxue-app`、`service.component=mobile-client`、`telemetry.relay=duxue-server`；relay 本身的 FastAPI span 是 `service.name=duxue-server`，带 `duxue.component=telemetry-relay`。

### 7.4 `service.name` 命名规范

`service.name` 是 Grafana 中区分三端的核心标签，统一命名约定：

| 端 | service.name | 说明 |
|----|-------------|------|
| duxue-server | `duxue-server` | FastAPI 主进程与 Celery Worker 共用，通过 `service.component` 区分 |
| duxue-cam | `duxue-cam` | Android 采集端 |
| duxue-app | `duxue-app` | Flutter Guardian 端 |

---

## 八、接入顺序建议

按业务价值和接入成本排序：

| 阶段 | 内容 | 预计工时 | 产出 |
|------|------|---------|------|
| **Phase 1** | 注册 Grafana Cloud + Server 端配置环境变量（OTEL 自动插桩） | 半天 | FastAPI/Celery/SQLAlchemy 全链路可见，零代码改动 |
| **Phase 2** | Server 端成本指标（`vlm.frames_analyzed_daily`、`batch.fallback_ratio`）+ 告警规则 | 半天 | 成本失控可被立刻发现 |
| **Phase 3** | App 端 dio Interceptor 注入 traceparent + dart-define 配置 | 半天 | App → Server 跨端链路串联 |
| **Phase 4** | Cam 端上传链路埋点 + 队列积压随心跳上报 | 半天 | 采集异常可追踪 |
| **Phase 5** | 其余 Server 自定义业务指标 + 完整告警覆盖 | 1 天 | AI 推理性能 + 队列积压告警 |

> Phase 1 全程不改业务代码，只加环境变量，可独立上线验证效果。
>
> **Phase 2 提前到移动端之前**，因为成本类问题发生时系统功能完全正常，只是账单翻几倍——没有指标就发现不了，而移动端的问题用户会直接反馈。
>
> 移动端 OTEL SDK 成熟度仍不足（Logs 信号在 Android/Flutter 侧为实验阶段，需手动注入 trace_id）。若 Phase 3/4 投入产出比不佳，可先只接 Sentry 收 crash，能覆盖绝大部分移动端排障需求。

---

*文档版本 v1.0 | 对应项目全系统可观测性设计*
