---
slug: implement-server-observability
created: 2026-09-12T07:25:52Z
status: done
---

# implement-server-observability spec

## 做什么 / 为什么
建立可在任意 OTLP 后端（Grafana Cloud 或私有 Alloy）运行的服务端可观测性基础：API、Celery、数据库和模型调用在 Grafana 可关联；以低基数业务指标监控成本、可靠性与性能；为 Agent 提供不泄露儿童原文的受控调试审计。

## 验收标准
- [ ] 未配置 OTLP 时服务维持现有行为；配置标准 `OTEL_*` 环境变量后，API 与 Celery 进程初始化 trace、metric、结构化日志导出，且资源属性能区分 API / worker / beat。
- [ ] `/companion/turn` 产生可关联的 Agent route / workflow / model spans；LLM span 带 `agent_type`、模型、结果、耗时、provider request id（若供应商返回）、token 用量（若供应商返回）和已脱敏错误类别，绝不含密钥、Authorization、图片 data URL、完整 context、思维链或原始儿童内容。
- [ ] 新增低基数 Metrics：Agent 回合/路由/Run 时延、LLM 调用/时延/fallback、VLM 帧量与 Batch fallback、帧接收结果、在线设备数、Celery 队列/任务耗时；`ward_id`、`run_id`、`thread_id` 不作 metric label。
- [ ] Agent 调试审计默认只记录哈希、长度、结构摘要与关联 ID；仅在显式调试开关和配置的短留存审计 sink 下记录脱敏截断内容，并有单元测试防止敏感字段泄漏。
- [ ] `.env.example`、生产 Compose / CI 部署约定、Grafana dashboard 与告警规则具备可部署模板；凭据全部从环境/Secret 读取，仓库不含实际凭据。
- [ ] 新增与受影响的服务端测试全绿，且现有完整服务端测试全绿。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 范围与边界：本 Feature 完成**服务端与 Grafana 可部署配置**；Flutter / Android OTEL 接入单独成 Feature，避免将未验证的移动 SDK 与生产服务端基础混在一次变更。默认同时支持 Grafana Cloud 和自托管 Alloy，只通过标准 OTLP 环境变量选择，不写入任何真实 endpoint/token。
- 影响文件：
  - `duxue-server/app/`：新增 observability 初始化、指标注册、结构化安全日志、Agent 审计 sink；在 FastAPI 生命周期、Celery、模型网关、推理任务与设备/帧路径接入。
  - `duxue-server/requirements.txt`、`Dockerfile`、`docker-compose.yml`、`.env.example`、部署 workflow：补齐实际所需插桩依赖、启动与配置约定。
  - `ops/observability/`（新增）：OTel Collector/Alloy 可选本地配置、Grafana dashboard JSON、告警规则与部署说明；不包含密钥。
  - `duxue-server/tests/`：新增 OTEL / Metric / Agent 安全审计测试；回归全量 pytest。
  - `docs/observability.md`：更新为“已实现 / 配置方式 / 运行验证”而非仅目标设计。
- 实施顺序：
  1. 建立可禁用、可测试的 OTEL bootstrap（traces / metrics / JSON logs），并用配置区分进程组件。
  2. 加自动插桩及 FastAPI/Celery 生命周期关联；补 HTTPX/OpenAI 外部调用 span。
  3. 在 Agent、VLM batch、帧/设备、Celery 关键点记录安全 spans、events 与低基数 metrics。
  4. 实现受控 Agent debug audit（默认摘要，显式开关才允许脱敏截断正文），以及防泄漏测试。
  5. 提供 Grafana dashboard、告警和 Cloud / Alloy 配置模板，更新部署说明。
  6. 运行目标测试、全量 pytest、静态检查与 `git diff --check`。
- 测试计划：
  - 单元测试验证 OTEL disabled / enabled 初始化、资源属性、各 metric 标签白名单。
  - 使用 in-memory exporter 验证 Agent span、模型成功 / 校验失败 / 超时 fallback 的属性和异常语义。
  - 审计测试断言原始用户内容、模型原文、授权头、密钥与图片 data URL 永不出现在默认日志、span 或 audit 记录。
  - 用 Mock 模型与 Celery 任务测试 VLM / Agent 指标增量；运行 `pytest tests -q`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架与配置模型
- [x] OTEL bootstrap、自动插桩和安全结构化日志
- [x] Agent / LLM span、event、metric 与审计 sink
- [x] VLM、采集健康、Celery metric
- [x] Grafana dashboard、告警、部署配置与文档
- [x] 单元 / 集成测试与全量回归
- [x] `git diff` review 与 `git diff --check`
- [x] Gate 2：用户于 2026-09-12 确认验收并允许归档

## 备注
- Grafana 是运行健康与排障平台；可识别儿童对话不得进入普通 Loki 或 metric labels。业务回放继续由现有 PostgreSQL `AgentStreamEvent` 等表承担。
- 验证：`cd duxue-server && .venv/bin/pytest tests -q` 于 2026-09-12 通过（112 passed）。OTLP bootstrap 烟测已验证初始化；当前 sandbox 禁止外网，实际 Grafana Cloud 接收需在部署环境检查。
