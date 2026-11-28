# 读学 Server

当前 MVP 已打通注册、Ward、设备邀请与绑定、预签名上传、帧元数据、分析、日报与周趋势。

```bash
# 在 duxue-server 目录，先使用与启动进程相同的环境配置更新数据库
# 默认读取同目录 `.env`；使用其它 ENV_FILE 时，迁移与启动都需指定它
.venv/bin/alembic upgrade head
# 只读验收：未应用全部迁移时返回非零退出码
.venv/bin/alembic current --check-heads

# 推荐启动方式
python main.py

# 等价
python -m uvicorn app.bootstrap.app:app --reload --host 0.0.0.0 --port 8000

python -m unittest tests.test_e2e -v
```

启动时会自动加载 `duxue-server/.env`（已存在的环境变量优先，不会被覆盖）。启动前会校验数据库、JWT 密钥、Redis 与 VLM API Key；使用 `STORAGE_BACKEND=oss` 时还会校验 OSS endpoint、bucket 与访问密钥，缺失任一项会在进程启动前报错。`STORAGE_BACKEND=local` 可用于测试，不要求 OSS 配置。`/frames/upload-url` 仍遵守“先取预签名 URL、再 PUT、最后提交元数据”的生产契约。

本地 Agent 功能使用测试 Admin 的已发布配置。首次启动和离线评测的配置方法见[Agent配置入口](agent_specs/README.md)。

开发、测试和生产环境更新代码后，都必须在启动 API/Worker 前运行同一环境的数据库迁移。`create_all()` 不会为已有表补列，不能替代 Alembic；生产环境必须禁用 `AUTO_CREATE_SCHEMA`。迁移命令：

```bash
alembic upgrade head
```

## 数据库与联调验收

服务端本地业务联调使用 `.env` 对应的 PostgreSQL `duxue-test`；正式服务使用 `.env.prod` 对应的 `duxue-prod`。现有进程环境变量优先于文件，执行迁移前必须确认实际数据库目标。Admin 自己的数据库连接由 `duxue-admin/.env` 管理，不能用它代替业务库检查。

每次涉及持久化结构的开发验收，须区分以下证据：

| 验证方式 | 数据库 | 能证明什么 |
|---|---|---|
| 快速自动测试 | 多数使用内存 SQLite，以当前 ORM 建表 | 用例与协议行为；不证明 PostgreSQL 迁移或联调库已升级 |
| PostgreSQL 集成测试 | 一次性本机实例或专用临时库 | PostgreSQL 约束、事务及迁移测试通过；不修改 `.env` 联调库 |
| 本地业务联调 | `.env` 对应的 `duxue-test` | 实际连接的库已迁移，并能运行当前业务链路 |

CI 设置 `TEST_GATEWAY_DATABASE_URL` 时，库名必须以 `duxue_gateway_test_` 开头，测试角色需要 `CREATEDB` 权限。该地址用于连接测试 PostgreSQL 服务；各测试模块创建独立临时数据库，迁移子进程与并发连接使用同一模块的临时地址，模块结束后删除该临时库。不得直接在共享入口库反复回退迁移，也不通过清空其他模块数据或绕过迁移的数据保护来保证测试通过。未设置该变量时，继续使用模块独占的本机临时 PostgreSQL 实例。

数据库变更收工前，先备份目标库，再执行迁移和只读版本检查：

```bash
# 在 duxue-server 目录，确认没有继承其它环境的 DATABASE_URL
ENV_FILE=.env .venv/bin/alembic upgrade head
ENV_FILE=.env .venv/bin/alembic current --check-heads
```

验收记录必须注明实际库名、迁移前后版本，并检查本轮关键表/字段及相关 PostgreSQL 用例。自动测试通过不能替代上述联调检查，也不能表述为“测试业务库已升级”。版本检查只核对 Alembic head，不检测任意手工结构漂移。Agent 配置另按[配置入口](agent_specs/README.md)检查实例的加载回执。

对于历史上由 `Base.metadata.create_all()` 创建、但从未使用 Alembic 的数据库，先备份数据库并核对当前表结构，再执行 `alembic stamp 20260804_01`，最后执行 `alembic upgrade head`。该过程会把 `owner` 转为 `admin`、`teacher/parent` 转为 `guardian`，并删除已废弃的 `birth_year` 与 `relation_type` 列。

## Docker

业务Compose连接现有RDS、Redis与OSS；当前正式Redis为同ECS独立持久化Docker服务，运行维护见[部署文档](../docs/deployment.md#业务redis与celery运行环境)。Agent发布源通过私有Docker网络连接Admin：

```bash
# Grafana 与可选 Langfuse 均由 `.env.prod` 中的环境变量直接配置。
ENV_FILE=.env.prod docker compose --profile tools run --rm migrate
ENV_FILE=.env.prod docker compose -f docker-compose.yml -f docker-compose.math.yml up -d --wait math-engine api worker solving-worker beat
```

如需启用 Langfuse Cloud，在 `.env.prod` 配置 `LANGFUSE_ENABLED=true`、项目 API key
与区域 URL；不需要 Compose override 或额外容器。详细字段与数据边界见
[`ops/observability/README.md`](../ops/observability/README.md)。

生产环境还需把 Admin Web 的实际 HTTPS Origin 填入 `CORS_ALLOW_ORIGINS`；不要使用 `*`，因为 Guardian 的 JWT 请求需要受限的浏览器跨域策略。

GitHub Actions 的构建与部署配置见仓库根目录的 [部署说明](../docs/deployment.md)。Server 相关改动合并至 `main` 后，镜像会推送至 GitHub Container Registry（GHCR），再在生产机执行迁移并重启服务。

在本机直接运行 Uvicorn 做 Ward 答疑联调时，异步求解由使用同一份 `.env` 的独立 worker 消费。在调试 Mac 的 `duxue-server` 运行 `MATH_ENGINE_MODE=subprocess .venv/bin/celery -A app.workers.celery_tasks worker -Q solving --pool=solo -n solving-test@%h -l info`。启动后会消费现存队列。排查单个 pending 档案时，先对照 `problem_dossiers.id`、Redis 消息中的 dossier ID 及 Celery 的 `inspect active_queues`；建档的租约时间无法证明 worker 已经取走任务。

本地 Compose 使用相同的测试 PostgreSQL 和调试 Redis 隧道，连接要求见[调试环境配置](../docs/deployment.md#本地调试共用-ecs-redis)。启动命令如下。

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --profile tools run --rm migrate
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```
