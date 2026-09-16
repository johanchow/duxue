# 服务端 `app` DDD 目录迁移

> 日期：2026-09-14
> 关联规范：`.agent/specs/ddd-server-structure.md`、`docs/technical/ddd-overview.md`

## 决策

- 服务端采用根目录 `app/`，而不是再引入 `src/duxue` 包名；仓库自身已是服务边界，保留已有的 `app` 导入语义并避免额外 `PYTHONPATH` 配置。
- HTTP/SSE/WebSocket 入口统一落在 `app.api`，并由 `bootstrap.app.create_app()` 创建 FastAPI、挂载 CORS、注册 API router 和观测能力。业务路由不再承担 ASGI 进程装配责任。
- `application` 与 `contexts` 保持同级。跨 Context 的 `CompanionCoordinator` 位于 `application/process_managers`；Companion 自有的路由策略和 Policy 位于 `contexts/companion/domain`。
- ORM、外部模型、对象存储、鉴权、Outbox、遥测和 Celery adapter 归入 `infrastructure` 或 `workers`。数据库表名、Alembic revision 与 `duxue.*` task 名称不变。

## 兼容性与验证

- Alembic 通过 `prepend_sys_path = .` 解析迁移与 metadata；测试直接从服务根加载 `app` 包。
- `ENV_FILE` 的相对路径必须相对 `duxue-server` 根目录解析。配置位于 `app/bootstrap` 时，配置根目录应使用 `parents[2]`；否则会悄悄错误地寻找 `app/.env`。
- 验证：`ENV_FILE=.env.test .venv/bin/pytest tests -q`，结果为 **127 passed**。
- `alembic history` 成功加载全部历史迁移。在线 `alembic check` 需要连接外部测试 RDS；当前沙箱 DNS 无法解析该 RDS，因此未在本环境执行在线 schema 比对。历史迁移中原先的 `from app import models` 已改为新的 persistence 模块路径。
