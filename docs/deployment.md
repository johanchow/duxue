# 部署与 CI/CD

仓库是 monorepo，GitHub Actions 工作流统一位于根目录 `.github/workflows/`：

| 工作流 | 触发条件 | 结果 |
|---|---|---|
| `server-ci.yml` | Server 相关 PR | Pytest、构建 Docker 镜像 |
| `server-deploy.yml` | Server 相关 `main` 推送或手动触发 | 推送 GHCR 镜像、远端迁移、启动 API/Worker/Beat、健康检查 |
| `app-ci.yml` | Guardian 相关 PR，或被 `app-release.yml` 调用 | Flutter 静态检查与测试 |
| `app-release.yml` | 每次 `main` 推送或在 `main` 手动触发 | 测试后签名 APK，保留 Artifacts，并发布下载页、APK 与最新版本元数据到 OSS |
| `download-ci.yml` | 下载页/发布脚本/相关工作流 PR，或被发布流程调用 | Node 页面分流测试、Python 发布及工作流回归 |
| `sites-pages.yml` | `sites/**` 合入 `main` 或手动触发 | 将演示目录发布到 GitHub Pages |

技术演示入口：<https://johanchow.github.io/duxue/>。仓库 Pages 已启用，发布来源为 GitHub Actions。工作流把 `sites/` 的内容作为站点根上传，公开路径不含目录名；相关文件合入 `main` 后自动更新。首次发布需等本工作流进入 `main` 并运行完成。

Guardian 的 Android 开发包由 `app-release.yml` 打出。iOS 与 Play 商店 AAB 仍由 Codemagic 负责；当前仓库未提交 `duxue-app/ios`，故不能配置 IPA。先在开发机确认应用标识后生成并提交该工程：

```bash
cd duxue-app
flutter create --platforms=ios --org <你的反向域名组织标识> .
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

工作流上传 Compose 与镜像，**不会**覆盖 `.env.prod`；Grafana 与可选 Langfuse 的
凭据都只保存在该文件中。

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

### Guardian APK

每次 PR 合入 `main`（以及其他 `main` 推送）都会自动测试、签名打包并发布；也可在 Actions 里对 `main` 手动 Run workflow。非 `main` 的手动运行跳过发布。包内 API 地址固定为 `https://duxuelai.xyz/api`。

下载入口：<https://download.duxuelai.xyz/>。二维码固定指向此地址。代码见 [`download-page/`](../download-page/) 与 [发布脚本](../scripts/publish-download.py)。PR #82 合入 `main` 后，[首次自动发布](https://github.com/johanchow/duxue/actions/runs/42239915167)成功，页面已从首次上线的 Build 20 自动更新到 Build 21。

发布顺序：Flutter 分析与测试、下载页/发布回归 → 签名 APK → 保存 Actions Artifact → 上传不可覆盖的版本化 APK → 核对大小与 SHA-256 元数据 → 上传下载页 → 最后更新 `latest.json`。任何前置步骤失败都不切换最新版本；历史包保留，不自动删除。签名密钥在最后的清理步骤移除。

OSS 公开对象布局：

```text
index.html
latest.json
releases/android/guardian-{version}-{build}-{commit7}-{sha256前12位}.apk
media/duxue-demo-{video|poster|captions}-{内容摘要}.{mp4|jpg|vtt}
```

页面脚本在发布时嵌入 HTML，页面以单个对象更新，不依赖第三方脚本。`index.html` 和 `latest.json` 使用 `Cache-Control: no-store, max-age=0`，页面读取元数据也禁用缓存；版本化 APK 使用长期不可变缓存及下载附件头。公开对象名不用 `+`：实测 OSS 静态托管会把它解析成空格；Actions Artifact 的名称仍沿用原有 `+` 规则。

页面支持 Android 浏览器自动尝试下载与手动下载、微信外部浏览器指引、网络失败重试；iOS 暂未开放。鸿蒙只展示 Android 兼容性提示，不自动下载。不承诺小米等浏览器必定提供商店入口；未上架安卓商店。

同一发布工作流通过 `guardian-release` 串行化。发布脚本拒绝让旧构建号覆盖较新的版本，拒绝同构建号对应不同 APK；重复发布相同安装包无需重传，失败后可重跑该次 workflow。若该 workflow 的构建号规则变更，仍必须遵守下文的构建号连续性约定。

本地验证（复用服务端虚拟环境的 OSS SDK / PyYAML）：

```bash
node --test download-page/*.test.js
duxue-server/.venv/bin/python -m unittest discover -s scripts/tests -v
cd duxue-app
flutter test test/release_version_test.dart
```

#### 下载页基础设施

2026-11-06 用户授权配置，首次发布和合入 `main` 后的自动发布均已验证。

| 配置 | 当前状态 |
|---|---|
| Bucket | `duxue-download-page`，华北2（北京），专用于公开下载资源 |
| 公网 Endpoint | `oss-cn-beijing.aliyuncs.com` |
| 下载域名 | `download.duxuelai.xyz`，已绑定 Bucket |
| DNS | 已添加 CNAME 到控制台推荐的 `duxue-download-page.cn-beijing.taihangpfm.cn`，`dig` 已验证生效 |
| 公开访问 | 已仅对下载 Bucket 关闭阻止公共访问，并保存公共读 ACL；写操作仍需认证，未修改其他 Bucket |
| 静态托管 | 默认首页 `index.html`，子目录首页未开启；HTTPS 页面、元数据和 APK 实测均为 200 |
| HTTPS | 0 元、90 天个人测试证书已签发并托管至 OSS，2027-02-04 到期；`curl` 证书校验通过（`ssl_verify_result=0`）。个人测试证书仅供开发测试，正式商用需更换适用证书 |
| 发布身份 | 已创建专用 RAM 用户 `duxue-download-publisher`，仅启用 AccessKey，不启用控制台登录 |
| 发布策略 | 已创建并绑定 `DuxueDownloadPublish`；仅允许 `acs:oss:*:*:duxue-download-page/*` 的 `oss:PutObject` / `oss:GetObject`，不授予删除或 Bucket 管理权限 |
| GitHub 凭据 | 已在 `production` Environment 新增并核对 `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET`，未改动现有签名及 ECS 凭据 |
| 商店链接 | 尚未上架 iOS 或安卓商店；首版只提供 APK，iOS 显示暂未开放 |

ECS 的 SSH 私钥不等于 OSS API 凭据。发布账号独立于现有业务 RAM 用户；不得将私钥或 AccessKey 写入仓库或公开下载 Bucket。

#### App 版本管理

- **版本名**以 `duxue-app/pubspec.yaml` 的 `version` 为唯一来源。例如 `0.2.0+1` 中的 `0.2.0`；发布功能时更新次版本，发布修复时更新补丁版本。合并代码不会自动修改版本名，也不会回写版本提交。
- **构建号**由 APK workflow 的 `GITHUB_RUN_NUMBER` 覆盖 pubspec 的 `+1`。同一 workflow 的新 run 递增，失败后重跑同一次 run 保留原号；编号允许有空缺。替换 workflow 或发布渠道时，须保证新构建号高于所有已分发的安装包。
- 登录页与家长「我的」页读取安装包的真实版本与构建号，CI 另注入短 commit SHA，例如 `版本 0.2.0 (Build 42) · abcdef1`。本地构建默认使用 pubspec 的完整版本，不显示未注入的 SHA。
- Actions Artifact 与 APK 同名，例如 `guardian-0.2.0+42-abcdef1` / `guardian-0.2.0+42-abcdef1.apk`，便于核对安装包。

日常合并仅产生新的构建号（如 `0.2.0+42` → `0.2.0+43`）；准备下一次版本发布时，在对应 PR 中更新 pubspec 的版本名。CI 不传 `--build-name`，防止覆盖该唯一来源。此策略不引入版本机器人或自动补丁升级。

| Secret | 用途 |
|---|---|
| `APP_KEYSTORE_BASE64` | `duxue-app.keystore` 的 Base64 |
| `APP_KEYSTORE_PASSWORD` | 密钥库口令 |
| `APP_KEY_ALIAS` | 别名，当前为 `duxue-app` |
| `APP_KEY_PASSWORD` | 密钥口令 |

本地没有 `KEYSTORE_FILE` 时，release 构建仍用 debug 签名，方便 `flutter run --release`。

Server 与 App 的 CI/CD 由上述工作流维护。Go采集网关已有 [Gateway CI](../.github/workflows/gateway-ci.yml)、本地三平台构建脚本及systemd模板；当前只构建测试与产物，不自动发布或部署。实际配置/运行见[家庭实验手册](camera-setup-guide.md)，架构与依赖边界见[采集设计](technical/design-gateway.md)。

### 官网演示视频素材

新版首页已在本地完成视频接入及四项能力展示，待用户验收，线上已恢复此前版本。发布顺序固定为：**本地修改与预览 → 用户确认 → 创建PR → 合入main → 发布流水线自动更新首页**。不得直接调用OSS写入首页替代该流程。

录制、合成与来源说明见 [视频制作脚本](../scripts/demo-video/README.md)，字幕和剪辑时间线在同目录 `shots.json`。媒体的公开路径、摘要、大小与类型唯一归属 [资源清单](../download-page/demo-assets.json)；大文件保存在被Git忽略的 `output/homepage-demo/`，不提交到仓库。

用户确认后如需准备新版媒体，`scripts/publish-website.py --directory output/homepage-demo` 只上传并核对不可变媒体，不写 `index.html`、APK或 `latest.json`。首页由main流水线调用 `publish-download.py:page_bytes()` 将下载和章节脚本内嵌，并替换清单中的媒体URL后发布；后续APK发布复用媒体，不重新合成视频。
