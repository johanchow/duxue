---
slug: implement-app-observability
created: 2026-09-12T14:02:10Z
status: done
---

# implement-app-observability spec

## 做什么 / 为什么
让 Flutter Guardian / Ward App 的关键用户体验可在 Grafana 中观测，并以 W3C Trace Context 串联 App → Server → Agent / LLM 链路；全程不把儿童内容、身份或 Grafana 凭据放入移动端。

## 验收标准
- [ ] App 的 Dio 请求自动创建 client span、注入 `traceparent`，并记录低基数 `app.http.duration` / `app.http.requests`；Server Tempo trace 能显示 App 端父 span 与 Server API 子 span。
- [ ] App 上报关键体验 Metrics / Events：登录与 token 刷新、报告加载、设备绑定、Agent 回合等待、ASR WebSocket、网络失败、路由加载、启动和未捕获异常；每个属性都经过白名单与低基数约束。
- [ ] 上报内容绝不包含 access/refresh token、邀请码、邮箱、ward/device/run/thread ID、用户输入、Agent 回复、ASR 转写、图片或完整 URL query；测试覆盖该边界。
- [ ] 移动端不内置 Grafana API token、OTLP Basic Auth 或其他长期密钥。Telemetry 通过已有 Bearer 登录态发往受控 Server relay；Server 校验身份、限流/过滤后以 `service.name=duxue-app` 转发至现有 OTLP 后端。
- [ ] Telemetry 在关闭或配置缺失时为 no-op；`dart-define` 仅注入非敏感环境、服务名、采样率与 relay URL。App 正常功能、离线与错误恢复不被 telemetry 失败阻断。
- [ ] App 单元 / Widget 测试、`flutter analyze` 全绿；Server relay 的测试与 `pytest` 全绿；Grafana 看板补齐 App 体验面板及告警模板。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 关键安全决策：**不把 Grafana Cloud 的 OTLP token 编入 Flutter 包。**`--dart-define` 不是密钥保护机制，release APK/IPA 仍可提取其值。采用“App → 已认证 Server relay → Grafana OTLP”的方案；relay 使用服务端已有 Grafana Secret，App 仅复用短期 Bearer token。
- 依赖选择：不引入移动端 OTLP SDK。App 只需要生成符合 W3C 的 `traceparent`、计时、白名单过滤与有界 relay 队列；OTLP 编码和长期 Grafana 凭据均留在 Server。这样避免为不直连 OTLP 的移动端增加未使用的 exporter 依赖与供应链面。
- 影响文件：
  - `duxue-app/pubspec.yaml`、`lib/core/telemetry.dart`（新增）、`lib/main.dart`、`lib/core/api_client.dart`、`lib/core/voice_transcription_service.dart`、关键页面 / Provider：bootstrap、Dio interceptor、路由 / 生命周期 / 未捕获错误、业务 Metric 与 Event。
  - `duxue-server/app/`、`schemas.py`、测试：新增认证 telemetry relay，严格 schema / 属性白名单 / 限流，使用独立 `duxue-app` OTLP Resource 转发 Trace、Metric、Log。
  - `ops/observability/grafana/`、`docs/observability.md`、`codemagic.yaml`：App dashboard/alert、构建时非敏感 dart-define 和部署说明。
- 实施顺序：
  1. 定义 App telemetry 合同、属性白名单、脱敏策略与 `dart-define` 配置；先写 contract / privacy 测试。
  2. 实现 Server authenticated relay 和独立 `duxue-app` OTLP providers，确保其不污染 `duxue-server` resource；测试拒绝敏感字段与未授权调用。
  3. 实现 Flutter telemetry runtime、内存有界队列、失败即丢弃策略和 W3C context；加入 Dio interceptor。
  4. 接入登录/刷新、报告/设备绑定、Agent、ASR、路由、启动和 Flutter 未捕获异常；只发枚举结果与耗时。
  5. 增加 Grafana App 面板和告警，更新 CI / 文档，跑全量验证。
- 测试计划：
  - Dart 单元测试验证 header 注入、Route 模板化、错误分类、属性过滤、无配置 no-op、失败不影响请求和队列上限。
  - Widget 测试验证 Agent / ASR / 页面事件只发送安全枚举与耗时。
  - FastAPI contract tests 验证 relay 鉴权、payload 限制、拒绝 token / 原文 / ID 字段，in-memory exporter 验证 `service.name=duxue-app`。
  - 运行 `flutter analyze && flutter test`，以及 `duxue-server` 的目标测试和全量 `pytest tests -q`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] App telemetry 合同、配置与隐私测试
- [x] Server authenticated relay 与 OTLP 转发测试
- [x] Flutter runtime、队列、W3C Trace Context 与 Dio interceptor
- [x] 关键页面、Agent、ASR、生命周期与错误事件
- [x] Grafana App dashboard / alert、构建与文档
- [x] App / Server 全量测试与静态检查
- [x] `git diff` review 与 `git diff --check`
- [ ] Gate 2：等待用户验收后归档 spec

## 备注
- App 端 Metrics 不采样；Trace 在 debug 为 100%、production 默认 20%。Relay 必须对单用户与单设备请求做速率限制，并在过载时丢弃 telemetry、绝不影响主业务请求。
- 验证：2026-09-13 `flutter analyze && flutter test` 通过；`duxue-server/.venv/bin/pytest tests -q` 通过（121 passed）。
