# 读学 Server

当前 MVP 已打通注册、Ward、设备邀请与绑定、预签名上传、帧元数据、分析、日报与周趋势。

```bash
# 推荐：读取同目录 `.env`（可用 ENV_FILE=指定其它文件）后启动 FastAPI
python main.py

# 等价
python -m uvicorn app.bootstrap.app:app --reload --host 0.0.0.0 --port 8000

python -m unittest tests.test_e2e -v
```

启动时会自动加载 `duxue-server/.env`（已存在的环境变量优先，不会被覆盖）。启动前会校验数据库、JWT 密钥、Redis 与 VLM API Key；使用 `STORAGE_BACKEND=oss` 时还会校验 OSS endpoint、bucket 与访问密钥，缺失任一项会在进程启动前报错。`STORAGE_BACKEND=local` 可用于测试，不要求 OSS 配置。`/frames/upload-url` 仍遵守“先取预签名 URL、再 PUT、最后提交元数据”的生产契约。

生产环境必须禁用 `AUTO_CREATE_SCHEMA`，然后在启动 API/Worker 前执行：

```bash
alembic upgrade head
```

对于历史上由 `Base.metadata.create_all()` 创建、但从未使用 Alembic 的数据库，先备份数据库并核对当前表结构，再执行 `alembic stamp 20260804_01`，最后执行 `alembic upgrade head`。该过程会把 `owner` 转为 `admin`、`teacher/parent` 转为 `guardian`，并删除已废弃的 `birth_year` 与 `relation_type` 列。

## Docker

生产环境连接外部 RDS、Redis 与 OSS，不会在 Compose 内再创建同名依赖：

```bash
ENV_FILE=.env.prod docker compose --profile tools run --rm migrate
ENV_FILE=.env.prod docker compose up -d api worker beat
```

生产环境还需把 Admin Web 的实际 HTTPS Origin 填入 `CORS_ALLOW_ORIGINS`；不要使用 `*`，因为 Guardian 的 JWT 请求需要受限的浏览器跨域策略。

GitHub Actions 的构建与部署配置见仓库根目录的 [部署说明](../docs/deployment.md)。Server 相关改动合并至 `main` 后，镜像会推送至 GitHub Container Registry（GHCR），再在生产机执行迁移并重启服务。

本地完整栈则额外叠加 `docker-compose.local.yml`：

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --profile tools run --rm migrate
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```
