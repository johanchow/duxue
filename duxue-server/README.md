# 读学 Server

当前 MVP 已打通注册、Ward、设备邀请与绑定、预签名上传、帧元数据、分析、日报与周趋势。

```bash
# 在 duxue-server 目录，先使用与启动进程相同的环境配置更新数据库
# 默认读取同目录 `.env`；使用其它 ENV_FILE 时，迁移与启动都需指定它
.venv/bin/alembic upgrade head

# 推荐启动方式
python main.py

# 等价
python -m uvicorn app.bootstrap.app:app --reload --host 0.0.0.0 --port 8000

python -m unittest tests.test_e2e -v
```

启动时会自动加载 `duxue-server/.env`（已存在的环境变量优先，不会被覆盖）。启动前会校验数据库、JWT 密钥、Redis 与 VLM API Key；使用 `STORAGE_BACKEND=oss` 时还会校验 OSS endpoint、bucket 与访问密钥，缺失任一项会在进程启动前报错。`STORAGE_BACKEND=local` 可用于测试，不要求 OSS 配置。`/frames/upload-url` 仍遵守“先取预签名 URL、再 PUT、最后提交元数据”的生产契约。

Agent功能还需准备Admin发布/导出快照，已取消仓库业务默认配置。首次运行和离线评测请先阅读[Agent配置入口](agent_specs/README.md)；环境参数、评测数据与Agent配置快照分别维护。

开发、测试和生产环境更新代码后，都必须在启动 API/Worker 前运行同一环境的数据库迁移。`create_all()` 不会为已有表补列，不能替代 Alembic；生产环境必须禁用 `AUTO_CREATE_SCHEMA`。迁移命令：

```bash
alembic upgrade head
```

对于历史上由 `Base.metadata.create_all()` 创建、但从未使用 Alembic 的数据库，先备份数据库并核对当前表结构，再执行 `alembic stamp 20260804_01`，最后执行 `alembic upgrade head`。该过程会把 `owner` 转为 `admin`、`teacher/parent` 转为 `guardian`，并删除已废弃的 `birth_year` 与 `relation_type` 列。

## Docker

业务Compose连接现有RDS、Redis与OSS；当前正式Redis为同ECS独立持久化Docker服务，运行维护见[部署文档](../docs/deployment.md#业务redis与celery运行环境)。Agent发布源通过私有Docker网络连接Admin：

```bash
# Grafana 与可选 Langfuse 均由 `.env.prod` 中的环境变量直接配置。
ENV_FILE=.env.prod docker compose --profile tools run --rm migrate
ENV_FILE=.env.prod docker compose up -d api worker beat
```

如需启用 Langfuse Cloud，在 `.env.prod` 配置 `LANGFUSE_ENABLED=true`、项目 API key
与区域 URL；不需要 Compose override 或额外容器。详细字段与数据边界见
[`ops/observability/README.md`](../ops/observability/README.md)。

生产环境还需把 Admin Web 的实际 HTTPS Origin 填入 `CORS_ALLOW_ORIGINS`；不要使用 `*`，因为 Guardian 的 JWT 请求需要受限的浏览器跨域策略。

GitHub Actions 的构建与部署配置见仓库根目录的 [部署说明](../docs/deployment.md)。Server 相关改动合并至 `main` 后，镜像会推送至 GitHub Container Registry（GHCR），再在生产机执行迁移并重启服务。

本地完整栈则额外叠加 `docker-compose.local.yml`：

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --profile tools run --rm migrate
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```
