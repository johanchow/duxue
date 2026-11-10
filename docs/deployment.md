# 部署与 CI/CD

仓库是 monorepo，GitHub Actions 工作流统一位于根目录 `.github/workflows/`：

| 工作流 | 触发条件 | 结果 |
|---|---|---|
| `admin-deploy.yml` | main上的Admin/Python执行代码更新或手动触发 | 测试、构建两个GHCR镜像、迁移独立管理库、更新Admin容器、HTTPS健康检查 |
| `admin-ci.yml` | Admin相关PR/推送及被部署流程调用 | 真实PostgreSQL约束/权限测试、类型检查与Next.js构建 |
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

首页只在用户点击下载按钮后下载APK，Android手机与浏览器手机模拟模式均不自动跳转；保留微信外部浏览器指引和网络失败重试。iOS暂未开放，鸿蒙显示Android兼容性提示。不承诺小米等浏览器必定提供商店入口；未上架安卓商店。

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


## Admin正式站点

目标域名`https://admin.duxuelai.xyz`，与现有Server同台ECS，部署目录`/home/duxue/duxue-admin`。现有API/Worker/Beat由原部署流程维护；本流程仅更新Admin和私有Python配置执行器。

阿里云已配置`admin`的A记录到ECS公网`47.107.176.107`（TTL 10分钟）。Nginx配置模板在[deploy目录](../duxue-admin/deploy/)：先用`admin.http.nginx.conf`提供HTTP-01验证路径，解析生效后申请独立证书，再切换`admin.nginx.conf`并执行`nginx -t`后reload。已有主站证书只包含apex/www，不用于Admin。HTTPS配置将80重定向443、把请求反代到127.0.0.1:3021，拒绝公网`/api/internal/`，调试请求超时300秒。

```bash
# 在ECS以root首次安装并签发；证书申请要求上述DNS已生效。
NEEDRESTART_MODE=l apt-get install -y --no-install-recommends certbot
certbot certonly --webroot -w /var/www/letsencrypt \
  -d admin.duxuelai.xyz --agree-tos --register-unsafely-without-email --non-interactive
# 安装SSL站点配置后校验并reload，保留主站配置。
nginx -t
systemctl reload nginx
systemctl enable --now certbot.timer
```

证书续期deploy hook先`nginx -t`再`systemctl reload nginx`。2026-11-09已完成独立证书签发、HTTPS安装与续期dry-run（含deploy hook）；certbot.timer已启用。公网HTTP跳转HTTPS、健康检查200、内部发布接口404、Chrome正式管理员登录及35文件目录读取通过。首次证书有效期至2027-02-07，后续自动续期。

正式部署文件为`docker-compose.yml`、`deploy.sh`、`images.env`和权限0600的`.env.prod`；目录归属duxue，模式0700。私有环境模板见[production.env.example](../duxue-admin/deploy/production.env.example)，数据库连接参数复用业务生产配置但库固定为`duxue-admin-prod`；测试库不迁移到正式库。共享内部密钥应独立随机生成，模型密钥仅给执行器；首次管理员单独初始化，不复用本地测试密码。凭据、pem、环境与本机`.local/production-bootstrap.json`均不得提交。

容器采用Node 22.21.1、Next standalone与无root用户；迁移CLI打成独立CommonJS包，包含pg/dotenv依赖，避免standalone文件追踪遗漏CLI依赖。运行镜像不含本机.env、测试凭据、浏览器数据或旧静态后台。Python执行器仅监听Docker内部8011端口，使用内存SQLite和本地临时存储；Node仅绑定宿主127.0.0.1:3021，交给Nginx终止TLS。

`Deploy Admin`复用既有GitHub `production`环境的部署SSH及GHCR拉取凭据，无新增Secret。合入main的相关变更触发：Admin CI → 构建/推送Admin与executor的提交SHA镜像 → 上传Compose/部署脚本 → 拉取镜像 → 正式管理库迁移 → 等待两个容器健康 → 公网HTTPS检查。仅代码进入main后自动部署才生效；开发分支不自动更新正式实例。

```bash
# ECS上检查/重启当前已记录版本；命令不会回显私有环境。
cd /home/duxue/duxue-admin
docker compose --env-file .env.prod --env-file images.env -f docker-compose.yml ps
docker compose --env-file .env.prod --env-file images.env -f docker-compose.yml up -d --wait
# 另可指定已验证的两个SHA镜像调用deploy.sh完成发布。
```

`images.env`记录最后健康镜像；更新失败时部署脚本恢复该镜像组合。迁移不自动回滚，后续迁移须保持对上个镜像的兼容。初次ECS无法连接Docker Hub时，可从[Docker官方ECR仓库](https://gallery.ecr.aws/docker/library/node)获取相同Node版本；日常正式构建由GitHub Actions完成，ECS只从GHCR拉取镜像。

正式环境首次验证脚本[production-smoke.mjs](../duxue-admin/scripts/production-smoke.mjs)在私有Docker网络执行：独立管理员登录/安全Cookie、未登录/跨站拒绝、35文件配置校验与真实意图模型调试、首次初始化发布、无业务写入的Workflow执行。首次管理员临时env在初始化后移除，登录凭据保存在本机忽略目录供用户领取。

## 业务Redis与Celery运行环境

2026-11-09现场修复后，业务Server使用同台ECS的标准Redis 7.4 Docker服务，实例名`duxue-redis`。Tair Serverless KV不支持现有Celery依赖的BRPOP与Pub/Sub，不能仅凭PING成功视为兼容；限制见[阿里云命令支持文档](https://help.aliyun.com/zh/redis/product-overview/commands-supported-by-tair-serverless-kv-instances)。原云端实例未释放，临时参数调整已恢复。

- 运维目录：ECS `/home/duxue/duxue-redis/`，独立Compose项目，镜像固定digest；与Server共享Docker私有网络`duxue-server_default`，无宿主/公网Redis端口。
- `redis.conf`包含随机密码，权限0600，由容器Redis用户读取；`data/`是持久化目录，AOF每秒落盘。内存上限128MiB且noeviction，容器内存上限256MiB；不要删除该目录或以普通磁盘清理清空它。
- Server连接在`/home/duxue/duxue-server/.env.prod`，`REDIS_HOST=duxue-redis`、`REDIS_USERNAME=default`，密码对应私有redis.conf；业务API/Worker/Beat均需重建才能加载修改。不要将Docker内部地址作为本机开发连接。
- 既有Server自动部署只更新API/Worker/Beat，保留这个独立Redis服务与持久目录；环境文件不随Git部署覆盖。重启Redis可在运维目录执行`docker compose up -d --wait`，不得对其执行清数据操作。
- 本次原云队列33条任务已复制并成功执行，原队列保留作恢复记录，不能再次无条件重放。仅root可读的队列快照与环境备份在`/root/`，不进入Git。
- 验收需同时验证Redis认证、Worker pong、真实无业务副作用任务的结果回写、Beat实际派发与业务任务成功，不能只看容器Up或API健康。AOF状态需为enabled且last_write_status=ok。

当前方案与ECS共用故障域，AOF everysec存在约一秒写入丢失窗口；如后续转回托管服务，需选择支持Celery所需完整命令的标准Redis/Tair规格，并安排队列与结果迁移。

## 生产Server接入Admin配置

业务可编辑Agent配置只由Admin维护，模式/缓存/离线快照参数见[配置入口](../duxue-server/agent_specs/README.md#运行模式)。本轮代码启用production加载，不改业务API协议。部署前必须完成以下准备，不能先替换运行容器再补配置：

1. Admin Node接入现有`duxue-server_default`私有网络，别名`duxue-admin`；执行器仍只接Admin网络。已有实例首次可在线增加该网络，后续由Admin Compose自动声明。公网Nginx继续拒绝`/api/internal/`。
2. ECS Server `.env.prod`设置`AGENT_CONFIG_SOURCE=admin`、`AGENT_CONFIG_SOURCE_URL=http://duxue-admin:3000/api/internal`、与Admin一致的`AGENT_ADMIN_INTERNAL_TOKEN`及`AGENT_CONFIG_CACHE=/app/var/admin/last-good.json`。勿回显密钥；修改前保留0600备份。
3. 从私有发布接口读取并验证当前prod发布，将完整`id/digest/bundle/environment/kind`缓存预备于`/home/duxue/duxue-server/var/admin/last-good.json`（0600）。Server Compose将这个目录挂到API/Worker/Beat；不得当构建缓存清除。
4. main发布拉取镜像、迁移后，先以新API镜像运行`python -m app.agent_specs preflight`。仅验证/缓存，不启动轮询、不冒充在线实例回执；网络短暂失败可用已有兼容prod缓存。预检失败保留原容器，等待处理配置；重试也用于等待Admin独立部署的网络就绪。
5. 预检通过才更新API/Worker/Beat；API启动同步加载，Celery子进程先恢复预热缓存、后台轮询。核对Admin实例回执、线上真实答疑及后台任务。原请求固定旧快照，新请求在成功加载后使用新版本；发布/回滚无需重建业务容器。

首次准备已在2026-11-09完成私有地址连通、prod发布验证、缓存预热与ECS环境文件更新；未重启现有业务容器，当前运行代码仍为566f4cc。待本轮代码合入main并自动部署后切换，不以预检容器或文件准备冒充业务已加载。已有R1发布的契约仍兼容，不重建或覆盖正式管理库。


## 数学执行器与配置升级

实现说明见 [数学核验设计](technical/tutoring-math.md)。本轮仅准备代码和CI，不操作正式发布或线上容器。

1. **先导出再升级控制执行器。** 从旧Admin导出当前工作草稿（若有）或当前发布快照；保留其id、digest、revision及environment。新代码契约不加载旧格式快照，避免升级后无法导出旧包。勿使用历史测试夹具替代当前配置。
2. 在Server目录生成升级候选（不覆盖源文件、不发布）：

   ```bash
   .venv/bin/python -m scripts.upgrade_math_bundle /path/current.json /path/math-candidate.json --enable
   ```

   不加`--enable`只迁移工具/协议清单，保留未授权状态。候选是draft，不能伪装成原发布；仅用于明确指定的离线评测或草稿导入。
3. 更新Admin控制执行器到新代码，在Admin目录执行：

   ```bash
   ADMIN_INIT_EMAIL=<管理员邮箱> npm run config:import-upgrade -- /path/math-candidate.json
   ```

   仅有效管理员、同环境可导入。原工作草稿id/revision或当前发布id/digest必须仍匹配；发布来源遇到已有草稿拒绝覆盖。原base_bundle/base_release_id保留，revision递增、旧校验/调试证据失效；不改变发布指针。
4. 先在测试环境启动数学执行器并让API/离线评测/Admin控制执行器通过`MATH_ENGINE_SOCKET`访问专用socket。API/Worker部署组合为：

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.math.yml build math-engine
   docker compose -f docker-compose.yml -f docker-compose.math.yml up -d --wait math-engine api worker beat
   ```

   配置见Compose：无网络、非root、只读根目录、无业务凭据、资源配额；专用volume仅共享socket。不要把Docker socket挂进业务容器。Admin控制执行器若独立容器运行，也需挂载同环境的socket volume并设置路径；本机调试可另启动本机执行器，但它不等价于生产容器隔离。
5. 在相同配置摘要下完成导师、备用模型、Judge真实调试及答疑回放后，由管理员正常发布；Server预检通过才更新服务。发布旧代码无法理解的新契约前，要安排Admin/Server兼容升级窗口，旧服务继续使用已固定的旧包，不把新包加载失败当作已切换成功。

Server CI安装数学测试依赖、构建独立镜像，并运行`python scripts/smoke_math_container.py duxue-math:ci`验证计算、UID、网络/文件系统与资源配置。Server Deploy构建同SHA数学镜像、上传Compose overlay并等待健康；没有合并/推送不会执行部署。回滚应同时恢复兼容的代码镜像与Admin完整发布包。
