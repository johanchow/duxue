# 部署与 CI/CD

仓库是 monorepo，GitHub Actions 工作流统一位于根目录 `.github/workflows/`：

| 工作流 | 触发条件 | 结果 |
|---|---|---|
| `server-ci.yml` | Server 相关 PR、`main` 推送 | Pytest、构建 Docker 镜像 |
| `server-deploy.yml` | Server 相关 `main` 推送或手动触发 | 推送 GHCR 镜像、远端迁移、启动 API/Worker/Beat、健康检查 |
| `cam-ci.yml` | Cam 相关 PR、`main` 推送 | Kotlin 单测、Lint、Debug APK |
| `cam-release.yml` | Cam 相关 `main` 推送、`cam-v*` Tag 或手动触发 | 签名 Release APK、更新正式下载包；Tag 额外创建 GitHub Release |
| `app-ci.yml` | Guardian 相关 PR、`main` 推送 | Flutter 静态检查与测试 |

Guardian 的商店构建继续由 Codemagic 负责；当前仓库未提交 `duxue-app/android` 和 `duxue-app/ios` 原生工程，故不能安全地配置 AAB/IPA 自动发布。先在开发机确认应用标识后生成并提交这些工程：

```bash
cd duxue-app
flutter create --platforms=android,ios --org <你的反向域名组织标识> .
```

生成后，配置 Android keystore、Apple Developer / App Store Connect 和 Google Play Service Account，再启用 Codemagic 的正式发布 workflow。不要把这些凭据、`.env.prod` 或原生签名文件提交到 Git。

## 远端固定布局（写在 workflow 里）

单生产机约定如下，**不要**再配成 GitHub Secrets：

| 项 | 固定值 | 说明 |
|---|---|---|
| `DEPLOY_SERVER_USER` | `duxue` | SSH 登录用户 |
| `DEPLOY_SERVER_PORT` | `22` | SSH 端口 |
| `DEPLOY_PATH` | `/home/duxue/duxue-server` | Server 部署目录；`ssh` 登录后 `cd ~/duxue-server` 即可见 |

首次上线前在 ECS 执行：

```bash
mkdir -p /home/duxue/duxue-server
# 将 .env.prod 放到该目录（永远不要提交 Git）
```

工作流只上传 `docker-compose.yml` 与镜像，**不会**覆盖 `.env.prod`。

SSH 使用 `StrictHostKeyChecking=no`（不要求配置 `DEPLOY_SERVER_KNOWN_HOSTS`）。适合当前单机、密钥登录的场景；换机或重装后一般也无需改 Secrets。

## GitHub Environments 与 Secrets

在 GitHub 只建立一个 `production` Environment，并在其中配置凭据。若要做到合并即自动上线，请不要为该 Environment 配置 required reviewers。

### Server deploy

GitHub Actions 使用自动提供的 `GITHUB_TOKEN` 推送镜像；无需创建 Registry 或额外 Variables。镜像名固定为 `ghcr.io/<GitHub 用户或组织>/duxue-server:<git-sha>`。

| Secret | 用途 |
|---|---|
| `DEPLOY_SSH_PRIVATE_KEY` | 部署用户 SSH 私钥 |
| `DEPLOY_SERVER_HOST` | **公网域名**（不要填裸 IP），例如 `duxuelai.xyz`。同时用于 SSH 与健康检查 |
| `GHCR_USERNAME` | 有权读取该 GitHub Packages 容器包的 GitHub 用户名或机器人用户名 |
| `GHCR_PULL_TOKEN` | 该账号的 classic PAT，最小权限为 `read:packages`；仅供 ECS 拉取私有 GHCR 镜像 |

健康检查**不再单独配置**：部署结束后请求

```text
https://$DEPLOY_SERVER_HOST/api/health
```

约定 Nginx 把 `/api` 反代到本机 `8000`。因此 `DEPLOY_SERVER_HOST` 必须是已备案、已上 HTTPS 证书的域名；填 IP 时证书校验通常会失败。

部署顺序：拉取镜像 → Alembic 迁移 → 启动 api/worker/beat → `GET https://$HOST/api/health`。

### Cam release

| Secret | 用途 |
|---|---|
| `API_BASE_URL` | 打进 APK 的公开 HTTPS API 地址，建议 `https://$DEPLOY_SERVER_HOST/api/` |
| `KEYSTORE_BASE64`、`KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD` | Android release 签名 |
| `DEPLOY_SSH_PRIVATE_KEY`、`DEPLOY_SERVER_HOST` | 与 Server 相同的 SSH 目标 |
| `DEPLOY_APK_PATH` | 远端 APK 目录，例如 `/var/www/duxue/downloads`（供 Nginx 静态下载） |

`DEPLOY_SERVER_USER` / `DEPLOY_SERVER_PORT` 已写死在 `cam-release.yml`。

Server 与 Cam 的相关改动合并到 `main` 后都会自动部署到 `production`。Cam 的 `cam-v*` Tag 额外创建带版本 APK 的 GitHub Release，便于回退。开发和测试仅在本地进行，不设远端 staging。
