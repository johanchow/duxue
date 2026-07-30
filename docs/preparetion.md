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
- **网络**：分配公网 IP，带宽按需（1~5 Mbps 起步）
- **登录方式**：选"密钥对"（不要用密码登录），创建或导入自己的 SSH 公钥

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
- **读写权限**：私有（不公开）
- **需记录**：Bucket 名称、Endpoint（内网地址）、地域

### 1.5 ACR 容器镜像服务

- **入口**：阿里云控制台 → 容器镜像服务 → 个人版（免费）
- **操作**：开通后创建一个命名空间（如 `duxue`）
- **地域**：与 ECS 同一地域
- **需记录**：Registry 地址（如 `registry.cn-hangzhou.aliyuncs.com`）、命名空间名称

### 1.6 域名

- **入口**：阿里云控制台 → 域名 → 注册域名
- **建议**：购买一个主域名，Server API 用子域名（如 `api.yourdomain.com`），Admin 用另一个子域名（如 `admin.yourdomain.com`）
- **重要**：国内 ECS 绑定域名必须完成 **ICP 备案**，周期 7~20 个工作日，**购买域名后立即提交备案**

### 1.7 SSL 证书

- **入口**：阿里云控制台 → 数字证书管理服务 → SSL 证书 → 免费证书申请
- **类型**：DV 域名型（免费），每个域名每年申请一次，有效期 1 年
- **需申请的域名**：`api.yourdomain.com`、`admin.yourdomain.com`（按实际域名申请）
- **备案通过后**再申请，否则审核会失败

### 1.8 RAM 子账号（用于 CI/CD 鉴权）

- **入口**：阿里云控制台 → 访问控制 RAM → 用户 → 创建用户
- **用途**：GitHub Actions 推送 Docker 镜像到 ACR 时使用，不要用主账号的 AccessKey
- **权限**：只授予 `AliyunContainerRegistryFullAccess`（ACR 读写）
- **需记录**：AccessKey ID、AccessKey Secret（创建时立即保存，之后无法再查看）

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
sudo mkdir -p /opt/duxue
sudo chown $USER:$USER /opt/duxue
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
scp -i ali-ecs.pem .env.prod duxue@47.107.176.107:/opt/duxue/.env.prod
```

### 3.7 阿里云安全组放行端口

在阿里云控制台 → ECS → 安全组 → 入方向规则，添加：

```
80    TCP   0.0.0.0/0   HTTP（Nginx）
443   TCP   0.0.0.0/0   HTTPS（Nginx）
1935  TCP   0.0.0.0/0   RTMP 推流（SRS）
22    TCP   你的本机IP   SSH（限制来源，不要开放 0.0.0.0/0）
```

> 1985（SRS HTTP API）只在容器内部访问，不需要对外开放。

---

## 四、AI 推理方案选择

Celery Worker 做 VLM 推理，有两种方案，**上线前必须确定**：

| 方案 | 说明 | 成本 | 推荐时机 |
|------|------|------|---------|
| **远程 API 调用** | 调用阿里云百炼 / 通义千问 API，不在本机跑模型 | 按调用量付费，无固定成本 | **早期推荐**，省去 GPU 费用和模型维护 |
| **本机推理** | 在 ECS 上下载 Qwen3-VL 模型文件本地运行 | 需要 GPU 规格 ECS（成本高），模型文件数十 GB | 业务量上来、成本可控后迁移 |

若选远程 API 方案，需要：

```
□ 开通阿里云百炼（bailian.console.aliyun.com）
□ 获取 API Key
□ 将 API Key 写入 .env.prod：
    VLM_API_KEY=sk-xxxxxxxxxxxxxxxx
    VLM_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    VLM_MODEL_NAME=qwen-vl-max
```

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

以下变量需要在 ECS 的 `/opt/duxue/.env.prod` 中配置，**此文件永远不提交 Git**：

```bash
# 数据库（阿里云 RDS 连接串）
DATABASE_URL=postgresql+asyncpg://用户名:密码@RDS内网地址:5432/duxue

# Redis（阿里云 Redis 连接串）
REDIS_HOST=redis.aliyun.com
REDIS_PORT=6379
REDIS_USERNAME=xxx
REDIS_PASSWORD=xxx

# OSS（阿里云对象存储）
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
OSS_BUCKET_NAME=
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com

# JWT 签名密钥（随机生成，长度 ≥ 32 位）
JWT_SECRET_KEY=

# AI 推理（阿里云百炼 / 通义千问）
VLM_API_KEY=sk-xxxxxxxxxxxxxxxx
VLM_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VLM_MODEL_NAME=qwen-vl-max

# 应用配置
APP_ENV=production
APP_BASE_URL=https://你的域名
SRS_HTTP_API=http://localhost:1985   # SRS 内网地址
```

> 生成随机 JWT 密钥：`python -c "import secrets; print(secrets.token_hex(32))"`

---

## 七、GitHub Secrets 配置

### 7.1 duxue-server 和 duxue-cam 共用（仓库级别）

进入 GitHub 仓库 → **Settings → Secrets and variables → Actions**：

| Secret 名称 | 值 | 说明 |
|------------|-----|------|
| `ACR_USERNAME` | 阿里云 RAM 子账号 AccessKey ID | 用于推送 Docker 镜像 |
| `ACR_PASSWORD` | 阿里云 RAM 子账号 AccessKey Secret | |
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
□ 购买云数据库 Redis
□ 开通 OSS，新建 Bucket
□ 开通 ACR，新建命名空间
□ 注册域名，提交 ICP 备案（备案期间可并行进行其他工作）
□ 申请免费 SSL 证书（备案通过后）
□ ECS 安装 Docker / Docker Compose / Git
□ ECS 安全组放行端口（80 / 443 / 1935 / 22）
□ 创建 /opt/duxue/ 工作目录
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
□ 确定 AI 推理方案，若用远程 API 则开通百炼并获取 API Key
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
□ 编写 /opt/duxue/.env.prod（见第六节）
□ 编写 /opt/duxue/srs.conf（SRS 流媒体配置）
□ 在 ECS 上执行第一次 git clone，验证 Deploy Key 有效
□ 执行 docker compose up -d，验证各容器启动正常
□ 执行 alembic upgrade head，验证数据库表结构初始化成功
```

### 阶段五：端到端验证

```
□ HTTPS 访问 API 域名，返回 200
□ RTMP 推流测试（1935 端口可达）
□ Guardian App 连接 staging 环境，完成注册/登录
□ Cam App 安装 APK，输入邀请码绑定设备，推流成功
□ 验证截帧 → AI 分析 → 报告生成全链路
```
