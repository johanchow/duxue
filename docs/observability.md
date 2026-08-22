# 读学系统 — 可观测性方案设计

> 版本 v1.0 | 覆盖：duxue-server · duxue-cam · duxue-app
>
> 全系统架构见：[docs/technical/ARCHITECTURE.md](./technical/ARCHITECTURE.md)

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
| **A. 纯 OpenTelemetry + Grafana** | OTEL SDK × 3 端 → Alloy → Loki / Tempo / Prometheus → Grafana | 三端统一标准；Traces/Logs/Metrics 在 Grafana 内互相跳转；无厂商锁定 | 移动端 OTEL SDK 较新，Logs 信号在 Android/Flutter 侧为实验阶段 |
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
                         │ OTLP（gRPC :4317 / HTTP :4318）
                         ▼
               ┌─────────────────┐
               │  Grafana Alloy  │  统一收集 & 路由
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
| `OTEL_SERVICE_NAME` | `duxue-app-debug` | `duxue-app` | 区分环境 |
| `OTEL_ENDPOINT` | `http://localhost:4318` | Grafana Cloud URL | OTLP HTTP 地址 |
| `OTEL_AUTH_HEADER` | 空 | `Basic <base64>` | 生产环境鉴权 |
| `OTEL_SAMPLE_RATE` | `1.0` | `0.2` | debug 全量采样 |

在 CI/CD 中，通过 `flutter build --dart-define=OTEL_ENDPOINT=xxx --dart-define=OTEL_AUTH_HEADER=yyy` 注入，不在代码仓库中存储敏感值。

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
