# 读学系统 — 上线前准备工作清单

> 本文档汇总发布上线前所有需要购买的云资源、注册的第三方账号、生成的密钥文件及配置项。
> 按"先完成基础设施 → 再配置 CI/CD → 最后验证"的顺序执行。

---

## 一、阿里云资源

### 1.1 ECS（云服务器）

- **入口**：阿里云控制台 → 云服务器 ECS → 创建实例
- **操作系统**：选 **Ubuntu 22.04 LTS 64位**（必须，后续所有命令基于此系统；不要选 CentOS / Alibaba Cloud Linux）
- **规格**：2 核 4G 起步，可后续升配
- **存储**：系统盘 40G，另挂一块数据盘用于存储日志和临时文件
- **网络**：分配公网 IP，带宽 **1~5 Mbps 起步即可**
- **登录方式**：选"密钥对"（不要用密码登录），创建或导入自己的 SSH 公钥

> **带宽为什么这么小就够**：帧图片由 Cam 端**预签名直传 OSS，不经过 ECS**，ECS 只承担元数据请求（每帧几百字节）与 App 的 API 调用。如果采用视频推流方案，单设备上行约 1500 kbps 且全部流经 ECS，1~5 Mbps 只够 1~2 台设备——带宽会是最先撞墙的地方。
>
> **2 核是否够**：第一期服务端不做任何本地视觉计算，ECS 只跑 API 与任务编排，2 核绰绰有余。第三期自部署模型时 GPU 走独立的按需启停实例，不占用这台 ECS。

### 1.2 RDS for PostgreSQL（数据库）

- **入口**：阿里云控制台 → 云数据库 RDS → 创建实例
- **引擎版本**：PostgreSQL 16
- **规格**：1 核 2G 起步
- **网络类型**：专有网络（VPC），与 ECS 选同一个 VPC，确保内网互通
- **白名单**：添加 ECS 的内网 IP，禁止 0.0.0.0/0
- **需记录**：内网连接地址、端口（5432）、数据库名、用户名、密码

### 1.3 云数据库 Redis

- **入口**：阿里云控制台 → 云数据库 Redis → 创建实例
- **版本**：Redis 7.x
- **规格**：1G 起步（标准版，单节点即可）
- **网络类型**：专有网络（VPC），与 ECS 同一 VPC
- **白名单**：添加 ECS 的内网 IP
- **需记录**：内网连接地址、端口（6379）、访问密码

### 1.4 OSS 对象存储

- **入口**：阿里云控制台 → 对象存储 OSS → 新建 Bucket
- **Bucket 名称**：如 `duxue-frames-prod`
- **地域**：与 ECS 同一地域（如华东1-杭州），内网传输免流量费
- **读写权限**：私有（不公开）。Cam 端通过服务端签发的**预签名 PUT URL** 上传，不下发长期凭证
- **跨域（CORS）**：需允许 Cam 端发起 PUT 请求，配置允许来源 `*`、允许方法 `PUT`、允许 Header `*`
- **生命周期规则**：为帧图片前缀（如 `frames/`）配置 **30 天后自动删除**。这是数据留存策略的执行方式，不要靠应用层逐个删
- **需记录**：Bucket 名称、Endpoint（内网 + 公网地址）、地域

> 公网 Endpoint 也要记录：预签名 URL 是给手机用的，必须走公网；而服务端 Worker 打包批次时读取帧图片走内网（免流量费）。两个地址都要配。

### 1.5 GitHub Container Registry（GHCR）

- **入口**：GitHub 仓库关联的 Packages 页面
- **操作**：无需预先创建仓库。首次合并到 `main` 时，GitHub Actions 会自动发布 `ghcr.io/<GitHub 用户或组织>/duxue-server`
- **需确认**：Package 设为 private，并允许当前仓库的 Actions 访问；ECS 使用 classic PAT（`read:packages`）拉取

### 1.6 域名

- **入口**：阿里云控制台 → 域名 → 注册域名
- **建议**：购买一个主域名，Server API 用子域名（如 `api.yourdomain.com`），Admin 用另一个子域名（如 `admin.yourdomain.com`）
- **重要**：国内 ECS 绑定域名必须完成 **ICP 备案**，周期 7~20 个工作日，**购买域名后立即提交备案**

### 1.7 SSL 证书

- **入口**：阿里云控制台 → 数字证书管理服务 → SSL 证书 → 免费证书申请
- **类型**：DV 域名型（免费），每个域名每年申请一次，有效期 1 年
- **需申请的域名**：`api.yourdomain.com`、`admin.yourdomain.com`（按实际域名申请）
- **备案通过后**再申请，否则审核会失败

### 1.8 GitHub Packages 拉取令牌（供 ECS 使用）

- **入口**：GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
- **用途**：ECS 拉取私有 GHCR 镜像；GitHub Actions 推送镜像使用内置 `GITHUB_TOKEN`，不需要 PAT
- **权限**：仅 `read:packages`，并确保令牌所属账号对该 Package 有读取权限
- **需记录**：GitHub 用户名与 PAT；PAT 只在创建时显示一次

> **备案说明**：ICP 备案是国内服务器绑定域名的法规要求，周期长，**优先提交**，其他准备工作可并行进行。

---

## 二、第三方平台账号

| 平台 | 用途 | 注册地址 | 费用 |
|------|------|---------|------|
| **GitHub** | 代码仓库 + CI/CD（server / cam） | github.com | 免费（私有仓库 2000 min/月） |
| **Codemagic** | Guardian App（Flutter 双端）CI/CD | codemagic.io | 免费 500 min/月，够早期使用 |
| **Apple Developer** | iOS App 签名 + TestFlight + App Store | developer.apple.com | $99/年，审核 1~2 个工作日 |
| **Google Play Console** | Android App 发布（Guardian App） | play.google.com/console | 一次性 $25 注册费 |

> Apple Developer 审核需要时间，**优先注册**。

---

## 三、ECS 服务器初始化

> 前提：ECS 操作系统为 **Ubuntu 22.04 LTS**，以下命令均基于此系统（`apt` 包管理）。

### 3.1 首次登录（用 root）

pem 文件权限必须设为 400，否则 SSH 会拒绝：

```bash
chmod 400 ali-ecs.pem
ssh -i ali-ecs.pem root@47.107.176.107
```

### 3.2 创建普通用户（不直接使用 root 操作）

以 root 身份登录后执行，创建一个可以 sudo 的普通用户：

```bash
# 创建用户（过程中会提示设置密码，按提示填写）
adduser duxue

# 加入 sudo 组，允许执行 sudo 命令
usermod -aG sudo duxue

# 将 root 的 SSH 公钥复制给新用户，让同一个 pem 文件也能登录新用户
mkdir -p /home/duxue/.ssh
cp /root/.ssh/authorized_keys /home/duxue/.ssh/
chown -R duxue:duxue /home/duxue/.ssh
chmod 700 /home/duxue/.ssh
chmod 600 /home/duxue/.ssh/authorized_keys
```

之后退出 root，改用新用户登录：

```bash
ssh -i ali-ecs.pem duxue@47.107.176.107
```

确认可以正常登录后，禁止 root 直接 SSH 登录（提高安全性）：

```bash
sudo nano /etc/ssh/sshd_config
# 找到下面这行，将值改为 no：
# PermitRootLogin no

sudo systemctl restart sshd
```

### 3.3 安装必要软件（以 duxue 用户执行）

```bash
# 更新软件包列表
sudo apt update

# 安装 Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录后 docker 命令才生效，执行：newgrp docker

# 安装 Docker Compose 插件
sudo apt install -y docker-compose-plugin

# 安装 Git
sudo apt install -y git

# 验证安装
docker --version
docker compose version
git --version
```

### 3.4 创建工作目录

```bash
mkdir -p /home/duxue/duxue-server
```

### 3.5 配置 Deploy Key（供 CI/CD 从 GitHub 拉代码）

```bash
# 在 ECS 上生成专用 SSH 密钥对
ssh-keygen -t ed25519 -C "ecs-deploy" -f ~/.ssh/ecs_deploy

# 查看公钥内容
cat ~/.ssh/ecs_deploy.pub
```

将公钥内容添加到 GitHub 仓库 → **Settings → Deploy keys → Add deploy key**，勾选"只读"（Allow write access 不勾选）。

### 3.6 上传 .env.prod

在本地执行（将生产环境变量文件上传到 ECS）：

```bash
scp -i ali-ecs.pem .env.prod duxue@47.107.176.107:/home/duxue/duxue-server/.env.prod
```

### 3.7 阿里云安全组放行端口

在阿里云控制台 → ECS → 安全组 → 入方向规则，添加：

```
80    TCP   0.0.0.0/0   HTTP（Nginx，仅用于跳转 443）
443   TCP   0.0.0.0/0   HTTPS（Nginx）
22    TCP   你的本机IP   SSH（限制来源，不要开放 0.0.0.0/0）
```

> **不需要开放 1935**。系统不接收 RTMP 推流，Cam 端通过 HTTPS 上传帧元数据、通过 OSS 预签名 URL 上传图片。少暴露一个明文端口也少一个攻击面。

---

## 四、AI 推理方案

### 4.1 演进路线：先 API，后自部署

| 阶段 | 推理方式 | 成本结构 | 进入下一阶段的条件 |
|------|---------|---------|-----------------|
| **第一期（当前）** | 百炼 Batch API + `qwen3-vl-flash` | 按帧数线性计费 | 积累到足够的真实场景标注数据 |
| 第二期 | 用第一期数据 fine-tune 小模型（2B~7B） | 一次性训练成本 | 在黄金集上不劣于 `qwen3-vl-flash` |
| 第三期（目标） | 自部署 fine-tune 模型，**按需启停云 GPU** | 按 GPU 运行时长计费 | — |

> **第三期必须是"按需启停"，不能是常驻实例。** 每日批量分析在夜间启动 GPU 跑十几分钟即可关闭。如果按 24 小时常驻计费，月成本很可能比 Batch API 贵一个量级以上——"自部署更便宜"这个前提就反过来了。

### 4.2 第一期方案：百炼 Batch API + `qwen3-vl-flash`

| 方案 | 说明 | 成本特征 | 结论 |
|------|------|---------|------|
| **百炼 Batch API** | 提交 JSONL 批量作业，24 小时内异步返回 | 实时价的 **50%**；不占用实时接口的并发配额 | ✅ **采用** |
| 百炼实时 API | 逐帧同步调用 | 全价，且多设备并发时会撞 QPS 限流 | 仅作 Batch 超时降级 |
| 自部署模型 | GPU 实例跑 Qwen3-VL | 需 GPU 规格实例，模型文件数十 GB | 第三期，需先有 fine-tune 数据 |

**为什么能用 Batch**：报告是次日查看的，系统里没有任何页面需要"这一帧刚分析完"。异步延迟在业务上不是妥协，是免费换来的 50% 单价。

Batch 支持的视觉模型（见 [批量推理文档](https://help.aliyun.com/zh/model-studio/batch-inference)）：`qwen3-vl-flash`、`qwen3-vl-plus`、`qwen-vl-plus`、`qwen-vl-max` 及其 latest 版本。**选 `qwen3-vl-flash`**——"看清坐姿和手在干什么"这个任务不需要 max 档，两者之间是量级差异。

### 4.3 开通步骤

```
□ 开通阿里云百炼（bailian.console.aliyun.com）
□ 获取 API Key
□ 确认 Batch 接口可用（控制台 → 批量推理，或直接用 OpenAI SDK 调 batches.create 测试）
□ 将配置写入 .env.prod（见第六节）
```

### 4.4 第一期的成本控制手段

**第一期不做帧过滤，所有帧全量送 VLM。** 原因见[服务端架构 §2.5](../duxue-server/docs/ARCHITECTURE.md)：门控与第二期 fine-tune 的数据需求冲突，且在第三期自部署形态下收益基本消失。

实际采用的四项手段，共同特点是**不依赖任何判断准确率**，因此零风险：

| 手段 | 效果 | 落地位置 |
|------|------|---------|
| **限制监控时段** | 最有效 | 只在实际需要观察的时段采集（如晚间两小时），而非全天挂机。由 guardian 在 App 中配置 |
| 采样间隔 15 秒（而非 5 秒） | ÷3 | `CAPTURE_INTERVAL_SECONDS`，服务端下发给 Cam 端 |
| Batch 接口 | ÷2 | `VLM_BATCH_BASE_URL` |
| 模型档位 flash + 分辨率 640×480 | 量级 | `VLM_MODEL_NAME`、Cam 端设置 |

> 上线后用 `duxue-server/scripts/0_quicktest.py` 按真实素材核算单 ward 的实际日成本。这个数字决定定价模型，也决定第三期自部署的优先级——如果算下来成本可忽略，自部署可以往后放。

---

## 五、签名密钥生成（一次性，务必备份）

### 5.1 duxue-cam（Android Cam App）

```bash
# 在本地执行一次
keytool -genkeypair \
  -alias duxue-cam \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -keystore duxue-cam.keystore

# 编码为 Base64（用于填入 GitHub Secrets）
base64 -i duxue-cam.keystore | pbcopy
```

```
□ 生成 duxue-cam.keystore
□ 备份到加密网盘（1Password / 飞书保险箱等），不得提交 Git
□ 将 Base64 内容填入 GitHub Secrets（见第七节）
```

### 5.2 duxue-app（Guardian App Android）

```bash
keytool -genkeypair \
  -alias duxue-app \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -keystore duxue-app.keystore
```

```
□ 生成 duxue-app.keystore
□ 备份到加密网盘
□ 上传到 Codemagic 控制台 → Teams → Code signing identities → Android keystores
```

### 5.3 duxue-app（iOS 签名）

```
□ 在 Apple Developer 后台创建 App ID（Bundle ID: com.duxue.app）
□ 在 App Store Connect 创建 App 记录
□ 生成 App Store Connect API Key
    路径：App Store Connect → Users and Access → Integrations → App Store Connect API
    权限：App Manager
    下载 .p8 文件（只能下载一次！），记录 Key ID 和 Issuer ID
□ 将 .p8 文件上传到 Codemagic → Teams → Code signing identities → iOS certificates
```

---

## 六、环境变量 / .env.prod

以下变量需要在 ECS 的 `/home/duxue/duxue-server/.env.prod` 中配置，**此文件永远不提交 Git**：

```bash
# ── 数据库（阿里云 RDS 连接串）
DATABASE_URL=postgresql+asyncpg://用户名:密码@RDS内网地址:5432/duxue

# ── Redis（阿里云 Redis 连接串）
REDIS_HOST=redis.aliyun.com
REDIS_PORT=6379
REDIS_USERNAME=xxx
REDIS_PASSWORD=xxx

# ── OSS（阿里云对象存储，帧图片）
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
OSS_BUCKET_NAME=duxue-frames-prod
OSS_ENDPOINT_INTERNAL=oss-cn-hangzhou-internal.aliyuncs.com  # Worker 读帧走内网，免流量费
OSS_ENDPOINT_PUBLIC=oss-cn-hangzhou.aliyuncs.com             # 预签名 URL 给手机用，走公网
OSS_PRESIGN_EXPIRE_SECONDS=300                               # 预签名 URL 有效期 5 分钟

# ── 认证
JWT_SECRET_KEY=                        # 随机生成，长度 ≥ 32
DEVICE_TOKEN_SECRET=                   # 设备 Token 签名密钥，与 JWT 密钥分开

# ── AI 推理（阿里云百炼，Batch 为主、实时为降级）
VLM_API_KEY=sk-xxxxxxxxxxxxxxxx
VLM_MODEL_NAME=qwen3-vl-flash
VLM_BATCH_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VLM_BATCH_COMPLETION_WINDOW=24h        # 平台允许 24h~336h
VLM_BATCH_SUBMIT_HOUR=22               # 每日提交批次的时刻
VLM_BATCH_FALLBACK_AFTER_HOURS=20      # 超时未完成则降级实时 API
VLM_REALTIME_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# ── 采集
CAPTURE_INTERVAL_SECONDS=15            # 下发给 Cam 端的抓拍间隔
HEARTBEAT_TIMEOUT_SECONDS=180          # 心跳超时即置 offline 并推送通知

# ── 数据留存
FRAME_RETENTION_DAYS=90                # 第一期 90 天以积累 fine-tune 训练数据
                                       # 对外提供服务前收紧至 30，并同步改 OSS 生命周期规则

# ── 应用配置
APP_ENV=production
APP_BASE_URL=https://你的域名
```

> 生成随机密钥：`python -c "import secrets; print(secrets.token_hex(32))"`
>
> 没有 `GATE_*` 系列变量——第一期不做帧门控，所有帧全量送 VLM。

---

## 七、GitHub Secrets 配置

### 7.1 duxue-server 和 duxue-cam 共用（仓库级别）

进入 GitHub 仓库 → **Settings → Secrets and variables → Actions**：

| Secret 名称 | 值 | 说明 |
|------------|-----|------|
| `GHCR_USERNAME` | 有读取容器包权限的 GitHub 用户名 | ECS 登录 GHCR |
| `GHCR_PULL_TOKEN` | classic PAT（仅 `read:packages`） | ECS 拉取私有镜像 |
| `ECS_HOST` | ECS 公网 IP 或域名 | |
| `ECS_USER` | SSH 登录用户名（如 ubuntu） | |
| `ECS_SSH_KEY` | 部署用 SSH 私钥内容 | 对应 ECS 上 authorized_keys 的公钥 |
| `TEST_DATABASE_URL` | CI 测试用数据库连接串 | 连开发环境 RDS |

### 7.2 duxue-cam 专属

| Secret 名称 | 值 |
|------------|-----|
| `KEYSTORE_BASE64` | duxue-cam.keystore 的 Base64 编码 |
| `KEYSTORE_PASSWORD` | Keystore 密码 |
| `KEY_ALIAS` | `duxue-cam` |
| `KEY_PASSWORD` | Key 密码 |

### 7.3 Codemagic 环境变量（duxue-app）

进入 Codemagic 控制台 → 对应应用 → **Environment variables**：

| 变量名 | 说明 |
|--------|------|
| `API_BASE_URL_PROD` | 生产环境 API 地址 |
| `API_BASE_URL_STAGING` | 开发/测试环境 API 地址 |
| `APP_STORE_CONNECT_KEY_IDENTIFIER` | Apple API Key 的 Key ID |
| `APP_STORE_CONNECT_ISSUER_ID` | Apple API Key 的 Issuer ID |
| `APP_STORE_CONNECT_PRIVATE_KEY` | 上传 .p8 文件 |
| `GCLOUD_SERVICE_ACCOUNT_CREDENTIALS` | Google Play Service Account JSON |

---

## 八、完整检查清单（按顺序执行）

### 阶段一：基础设施（优先完成）

```
□ 购买 ECS（Ubuntu 22.04），购买 RDS for PostgreSQL
□ 购买云数据库 Redis
□ 开通 OSS，新建 Bucket
    └─ 配置 CORS（允许 PUT）
    └─ 配置生命周期规则（frames/ 前缀 90 天后删除）
    └─ training/ 前缀不挂生命周期规则（训练集候选帧长期保留）
□ 确认 GitHub Packages 已启用；准备 ECS 拉取私有 GHCR 镜像的 `read:packages` PAT
□ 注册域名，提交 ICP 备案（备案期间可并行进行其他工作）
□ 申请免费 SSL 证书（备案通过后）
□ ECS 安装 Docker / Docker Compose / Git
□ ECS 安全组放行端口（80 / 443 / 22，不需要 1935）
□ 创建 /home/duxue/duxue-server/ 工作目录（与 server-deploy.yml 中 DEPLOY_PATH 一致）
□ 配置 ECS Deploy Key 并添加到 GitHub 仓库
```

### 阶段二：账号与密钥

```
□ 注册 Apple Developer（$99/年，尽早，有审核周期）
□ 注册 Google Play Console（$25，一次性）
□ 注册 Codemagic，连接 duxue-app 仓库
□ 生成 duxue-cam.keystore，备份，编码 Base64
□ 生成 duxue-app.keystore，备份，上传 Codemagic
□ 生成 Apple App Store Connect API Key，下载 .p8 备份
□ 开通阿里云百炼，获取 API Key
□ 验证 Batch 接口可用（用 OpenAI SDK 调 batches.create 跑一条测试请求）
```

### 阶段三：CI/CD 配置

```
□ 配置 GitHub Secrets（server + cam 共用部分）
□ 配置 GitHub Secrets（cam 专属签名密钥）
□ 配置 Codemagic 环境变量（app 签名 + API 地址）
□ 编写 .github/workflows/deploy-server.yml
□ 编写 .github/workflows/rollback-server.yml
□ 编写 duxue-cam 的 GitHub Actions workflow
□ 编写 duxue-app 的 codemagic.yaml
```

### 阶段四：写入生产配置

```
□ 编写 /home/duxue/duxue-server/.env.prod（见第六节）
□ 确认 .gitignore 覆盖 .env* 通配（并对 .env.example 加白名单例外）
□ 在 ECS 上执行第一次 git clone，验证 Deploy Key 有效
□ 执行 docker compose up -d，验证 api / worker / beat 三个容器启动正常
□ 执行 alembic upgrade head，验证数据库表结构初始化成功
□ 确认所有业务表都有 tenant_id 且 RLS 策略已启用
```

### 阶段五：端到端验证

```
□ HTTPS 访问 API 域名，返回 200
□ Guardian App 连接生产环境，完成注册/登录/创建 ward
□ Cam App 安装 APK，输入邀请码绑定设备
□ 验证帧上传链路：申请预签名 URL → PUT 到 OSS → 提交元数据 → frames 表有记录
□ 验证断网补传：飞行模式 5 分钟后恢复，确认积压帧按时间序补齐
□ 验证心跳掉线：强制停止 Cam App，确认 3 分钟内设备置 offline
□ 验证 Batch 链路：手动触发一次批次提交，确认 analysis_batches 状态流转到 completed
□ 验证报告生成：确认 frame_predictions → behavior_segments → reports 全链路产出
□ 验证跨租户隔离：用 A 租户账号尝试访问 B 租户的 ward，必须返回 403/404
```

### 阶段六：上线后的第一周

```
□ 用真实素材核算单 ward 的实际日成本，据此确认定价模型与第三期优先级
□ 观察 duxue.batch.fallback_ratio，确认 Batch 实际时延可靠
□ 检查 classifier/categories.yaml 在真实机位下的分类效果，重写依赖"目光"的参考短句
□ 开始人工筛选训练集候选帧（标记 training_candidate=true），为第二期 fine-tune 备料
□ 建立黄金标注集（200~300 帧，覆盖各行为类别与不同光照/坐姿），接入 CI 回归
```
