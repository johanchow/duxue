# 部署与 CI/CD

仓库是 monorepo，GitHub Actions 工作流统一位于根目录 `.github/workflows/`：

| 工作流 | 触发条件 | 结果 |
|---|---|---|
| `server-ci.yml` | Server 相关 PR、`main` 推送 | Pytest、构建 Docker 镜像 |
| `server-deploy.yml` | Server 相关 `main` 推送、`server-v*` Tag 或手动触发 | 推送 GHCR 镜像、远端迁移、启动 API/Worker/Beat、健康检查 |
| `cam-ci.yml` | Cam 相关 PR、`main` 推送 | Kotlin 单测、Lint、Debug APK |
| `cam-release.yml` | `cam-v*` Tag 或手动触发 | 签名 Release APK、上传下载服务器、创建 GitHub Release |
| `app-ci.yml` | Guardian 相关 PR、`main` 推送 | Flutter 静态检查与测试 |

Guardian 的商店构建继续由 Codemagic 负责；当前仓库未提交 `duxue-app/android` 和 `duxue-app/ios` 原生工程，故不能安全地配置 AAB/IPA 自动发布。先在开发机确认应用标识后生成并提交这些工程：

```bash
cd duxue-app
flutter create --platforms=android,ios --org <你的反向域名组织标识> .
```

生成后，配置 Android keystore、Apple Developer / App Store Connect 和 Google Play Service Account，再启用 Codemagic 的正式发布 workflow。不要把这些凭据、`.env.prod` 或原生签名文件提交到 Git。

## GitHub Environments 与 Secrets

在 GitHub 建立 `staging`、`production` 两个 Environment，生产环境必须启用 required reviewers。将部署凭据放在对应 Environment secrets，避免测试环境工作流读取生产凭据。

### Server deploy

| Secret | 用途 |
|---|---|
| `DEPLOY_SSH_PRIVATE_KEY` | 专用部署用户的 SSH 私钥 |
| `DEPLOY_SERVER_KNOWN_HOSTS` | 固定的服务器 SSH host key（`ssh-keyscan -H <host>` 获取后人工核对） |
| `DEPLOY_SERVER_HOST` / `DEPLOY_SERVER_PORT` / `DEPLOY_SERVER_USER` | SSH 目标 |
| `DEPLOY_PATH` | 远端部署目录，目录内预置 `.env.prod` |
| `GHCR_USERNAME` / `GHCR_PULL_TOKEN` | 远端拉取私有 GHCR 镜像的最小权限凭据（`read:packages`） |
| `DEPLOY_HEALTHCHECK_URL` | 公网 HTTPS API 根地址，例如 `https://api.example.com` |

首次部署前，在远端创建 `DEPLOY_PATH`，写入权限为部署用户，并只手工放置 `.env.prod`。工作流只上传 Compose 文件和镜像，不会覆盖该环境文件。部署顺序固定为：拉取镜像 → Alembic 迁移 → 启动服务 → `GET /health`。

### Cam release

| Secret | 用途 |
|---|---|
| `API_BASE_URL` | 对应环境的公开 HTTPS API 地址 |
| `KEYSTORE_BASE64`、`KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD` | Android release 签名 |
| `DEPLOY_SSH_PRIVATE_KEY`、`DEPLOY_SERVER_KNOWN_HOSTS` | APK 下载站 SSH 凭据 |
| `DEPLOY_SERVER_HOST` / `DEPLOY_SERVER_PORT` / `DEPLOY_SERVER_USER` | SSH 目标 |
| `DEPLOY_APK_PATH` | 远端 APK 目录，例如 `/var/www/duxue/downloads` |

Server 的 `main` 推送自动部署到 `staging`；`server-v1.0.0` 这类 Tag 自动部署到 `production`。Cam 使用 `cam-v1.0.0` Tag 发布生产包；如需先发布测试环境，使用 workflow dispatch 并选择 `staging`。端专属 Tag 避免一次 Tag 同时发布多个端。
