# 平台

事实源：[design-server](../../docs/technical/design-server.md)、[ddd-overview](../../docs/technical/ddd-overview.md)、[design-agent](../../docs/technical/design-agent.md)、[agent_specs/README](../../duxue-server/agent_specs/README.md)。

## 目标

服务端按 Interface → Application → Domain → Infrastructure 分层。AI 调用走组件网关。Workflow / Agent / Gate / Tool 用本地 JSON 描述运行装配，领域规则留在代码。

## 状态

- 已落地：根目录 `app/` 分层、按 Context 拆 router、组件网关、声明式 Workflow、生产库 `duxue-prod`。
- `design-agent.md` 若写「目标契约，不是当前 JSON」，以文首「迁移已实现」和 `agent_specs/` 为准。
- 具体模型名以各 JSON 的 `models` 为准，不记在这里。

## 决策

- 不引入 `src/duxue` 包。ORM、OSS、鉴权、Outbox、遥测、Celery 归 infrastructure 或 workers。表名与 `duxue.*` task 名不变。
- 一个 path/method 只注册一次。共享 HTTP 辅助放 `v1/common.py`。应用装配只在 `bootstrap`。
- 组件配置随代码发布。安全裁决、答案保护、事务不进 JSON。Workflow 只编排 Agent / Gate / 代码步骤。`models` 数组顺序即尝试顺序。
- 模型返回的闭集每个取值只对应一种结果。失败映射到已有的「不可用」值，不另造同义词。
- 模型名写进 JSON。端点、密钥、超时、总开关留环境变量。`AI_MODEL_OVERRIDES` 只按组件 ID 应急覆盖，`tutoring.*` 禁止覆盖，非法值启动失败。
- JSON 组件关闭思考（`enable_thinking=false`）。线上已设的 `VLM_MODEL_NAME` / `ASR_MODEL` 不被代码默认值覆盖。实时 ASR 保持 `qwen3-asr-flash-realtime`，钉到 `2026-02-10` 会在北京空间把会话断开。
- 非 production 时服务端读、查、删 OSS 走公网 endpoint。预签名上传始终公网。生产继续内网。
- DDD 管业务语义与用例事务。Workflow 的节点、恢复、模型失败由 agent 设计管。

## 注意

- 2026-10-31 用户确认采集产品化路线改为标准网络摄像头 + 共享本地网关；单摄像头/家庭 Wi-Fi/电脑先验证。技术事实源已重写为 [采集设计](../../docs/technical/design-gateway.md)，旧手机实现不再作为目标方案。网关、机构能力尚未完成。注意现有心跳只反映云端连通，时间修正会改写超过24h的历史帧，元数据重试必须复用同一 OSS key。
- 测试分层见 design-server。SQLite 不能代替 PostgreSQL 约束与迁移测试。测试必须在导入应用前 `OTEL_SDK_DISABLED=true`，并 mock 外网模型。
- `alembic check` 里 LangGraph checkpoint 表与应用 ORM 的差异不要当成业务表缺失。
- `ENV_FILE` 相对 `duxue-server` 根解析。纯文本组件会把图片 part 换成占位文字。
- 答疑首字延迟在非流式下不满足 P90&lt;1.2s。流式、成本归集、provider 回退未作为完成项。

- 2026-11-01 用户授权移除旧采集实现：删除 Android 采集工程、专用 CI/发布流程及构建脚本依赖，同步接入/部署/产品导航。服务端设备、帧、校时与 OSS 能力为新网关复用，不删除兼容字段或历史迁移；网关仍待实现。移动端构建脚本用隔离的 Flutter 替身做回归测试，避免删除 Cam 后仍访问旧目录。

- 2026-11-01 家庭验证接入简化：用户确认人工配置 camera_id、RTSP 地址/本地账号与 ward_id，取消绑定码/逐摄像头云端 Token，改为预配置网关凭证与 Ward 白名单。已按仓库 DDD skill 重写 [采集架构](../../docs/technical/design-gateway.md) 为唯一目标事实源；网关、新认证/幂等上传/健康 API 与迁移均待实现。不要将旧逐设备认证接口视为支持新配置。

- 2026-11-01 网关设计复核：入口重命名为 [design-gateway](../../docs/technical/design-gateway.md)，按网关自身调用与云端间接数据关系区分领域依赖；移除本次无须新增的分析事件/任务设计，保留现有云端Memory事实契约。模型清单显式列出根实体、值对象、服务/Factory、Repository和事件；不为齐全而虚构Domain Service。

- 2026-11-01 用户要求统一聚合根命名：网关文档与仓库 DDD skill/template 使用 Aggregate Root（聚合根）及其设计，不再使用设计卡片作为表头；聚合仍表示一致性边界，聚合根表示唯一修改入口，两者语义保持区分。
