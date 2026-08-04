# 读学Eye（Cam App）— CI/CD 方案

> 版本 v1.0 | 平台：Android（Kotlin）

---

## 一、方案选择：GitHub Actions

### 为什么选 GitHub Actions

Cam App 是纯 Android 项目，构建环境只需 Linux（`ubuntu-latest`），不需要 macOS。这使得 GitHub Actions 成为最轻量、成本最低的选择。

| 工具 | Android 支持 | 费用 | 配置复杂度 | 说明 |
|------|------------|------|----------|------|
| **GitHub Actions** | ✅ ubuntu-latest 原生 | 公开仓库免费；私有仓库 2000min/月免费 | 低 | 最适合纯 Android 项目 |
| Codemagic | ✅ 支持 | $95/月起（Cam App 用不上 iOS 构建） | 低 | 适合 Flutter 双端，单 Android 溢价 |
| Fastlane | ✅ 支持 | 开源免费，但需自维护 Runner | 高 | 功能强但运维成本高 |
| Bitrise | ✅ 支持 | $36/月起 | 中 | 对纯 Android 来说性价比不如 Actions |

**选择 GitHub Actions 的核心原因：**

1. **零额外成本**：Android 构建只需 Linux 环境，GitHub Actions 的 `ubuntu-latest` Runner 完全够用，私有仓库每月 2000 分钟免费额度，单次 Android 构建约 5~8 分钟
2. **与代码仓库深度集成**：PR 检查、Tag 触发发布、构建产物上传全部在同一平台，无需维护第三方账号
3. **配置即代码**：流水线配置文件（`yml`）与代码一同版本管理，变更可追溯
4. **APK 直接上传到服务器**：Cam App 走自托管分发，GitHub Actions 执行 `scp` 上传到读学服务器是最直接的路径

---

## 二、接入准备（从零到跑通 CI 的完整步骤）

### 第一步：生成 Android Keystore

在本地执行一次，生成签名密钥文件。**此文件只生成一次，务必妥善备份。**

```bash
keytool -genkeypair \
  -alias duxue-cam \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -keystore duxue-cam.keystore
```

生成后：
- 将 `duxue-cam.keystore` 备份到加密网盘（如 1Password），**不要提交到 Git**
- 在 `.gitignore` 中加入 `*.keystore`

### 第二步：将 Keystore 编码为 Base64

GitHub Secrets 不能存二进制文件，需先编码：

```bash
base64 -i duxue-cam.keystore | pbcopy  # macOS，结果复制到剪贴板
```

### 第三步：在 GitHub 仓库配置 Secrets

进入 GitHub 仓库 → **Settings → Secrets and variables → Actions → New repository secret**，依次添加：

| Secret 名称 | 值 | 说明 |
|------------|-----|------|
| `KEYSTORE_BASE64` | 上一步的 Base64 字符串 | Keystore 文件内容 |
| `KEYSTORE_PASSWORD` | 生成时设置的 store 密码 | |
| `KEY_ALIAS` | `duxue-cam` | 生成时设置的 alias |
| `KEY_PASSWORD` | 生成时设置的 key 密码 | |
| `DEPLOY_SSH_PRIVATE_KEY` | 部署用 SSH 私钥（见下一步） | 用于上传 APK 到服务器 |
| `DEPLOY_SERVER_HOST` | 读学服务器 IP 或域名 | |
| `DEPLOY_SERVER_USER` | 服务器 SSH 用户名 | |

### 第四步：配置服务器部署 SSH 密钥

在本地生成一对专用于 CI 部署的 SSH 密钥（不要复用个人 SSH 密钥）：

```bash
ssh-keygen -t ed25519 -C "github-actions-duxue-cam" -f ~/.ssh/duxue_cam_deploy
```

- **公钥**（`duxue_cam_deploy.pub`）：追加到服务器的 `~/.ssh/authorized_keys`
- **私钥**（`duxue_cam_deploy`）：填入上一步的 `DEPLOY_SSH_PRIVATE_KEY` Secret

服务器上为部署用户只授予写入 `downloads` 目录的权限，其他目录不可写，降低风险。

### 第五步：创建 GitHub Actions 工作流文件

本仓库是 monorepo，工作流必须建在**仓库根目录**（而不是 `duxue-cam/.github`）：

```
duxue/
└── .github/
    └── workflows/
        ├── cam-ci.yml        # PR / main：测试、Lint、Debug APK
        └── cam-release.yml   # main：签名 APK + 上传生产下载站；cam-v* Tag 额外创建 Release
```

文件已随代码提供；提交到 GitHub 后 Actions 会自动识别。完整 Secret 清单见仓库根目录的 [`docs/deployment.md`](../../docs/deployment.md)。

### 第六步：验证流水线

1. 提交任意 PR，确认 `test.yml` 触发并通过
2. 推送一个测试 Tag（如 `v0.0.1-test`），确认 `release.yml` 触发
3. 检查 GitHub Actions 页面的执行日志，确认 APK 构建成功并上传到服务器
4. 从服务器下载 APK 安装到手机，验证签名和功能正常

---

## 三、流水线设计

### 触发策略

| 分支 / 事件 | 触发动作 | 说明 |
|------------|---------|------|
| PR 提交 | 只跑测试 + 静态检查 | 保证合并前质量 |
| `main` 分支 push | 构建 Release APK + 签名 + 更新正式下载地址 | 合并即上线 |
| Tag `cam-v*`（如 `cam-v1.2.0`） | 构建 Release APK + 签名 + 更新正式下载地址 + 创建 GitHub Release | 留存可回退版本 |

### 流水线阶段

```
代码提交
  └─ 阶段一：质量门禁
       ├─ Kotlin 编译检查（./gradlew compileDebugKotlin）
       ├─ 单元测试（./gradlew test）
       └─ Lint 检查（./gradlew lint）

  └─ 阶段二：构建
       ├─ ./gradlew assembleRelease
       └─ 签名（Keystore 从 GitHub Secrets 注入）

  └─ 阶段三：分发
       ├─ 上传 APK 到读学服务器静态目录（scp）
       ├─ 更新下载页二维码对应链接
       └─ 创建 GitHub Release（附带 APK 产物）
```

---

## 四、APK 分发方案

Cam App 的分发与普通消费类 App 不同，**走自托管下载而非应用商店**，这是与 Guardian App CI/CD 最核心的差异。

### 分发流程

```
CI 构建完成
  └─ APK 上传到读学服务器
       └─ 服务器静态目录：/var/www/duxue/downloads/cam-latest.apk
            └─ 下载页展示二维码（指向该 APK 地址）
                 └─ Guardian 在读学 App 中点击"下载读学Eye"
                      └─ 扫码 → 浏览器下载 → 安装
```

### 版本管理策略

- `cam-latest.apk`：始终指向最新稳定版，Guardian 扫码下载永远是最新版本
- `cam-v1.2.0.apk`：历史版本归档，存放在 GitHub Release，供回退使用
- 每次发版自动覆盖 `cam-latest.apk`，无需用户重新扫描二维码

### 是否需要上国内应用商店

短期内**不建议**将 Cam App 上架应用商店，原因：

1. **受众明确**：Cam App 只有"配置摄像手机"这一个使用场景，用户不会主动在应用商店搜索它
2. **上架成本高**：华为/小米商店需要软著、营业执照、应用备案，审核周期 1~3 个月
3. **审核风险**：App 申请摄像头 + 后台常驻 + 自启动等高危权限，商店审核可能要求额外说明
4. **体验更好**：自托管分发链路更短，版本更新无需等待商店审核

---

## 五、签名与密钥管理

Android 签名是发版的关键环节，Keystore 丢失意味着无法更新已安装的 App。

### 存储方式

- Keystore 文件以 **Base64 编码**存入 GitHub Secrets（`KEYSTORE_BASE64`），构建时解码还原
- `KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD` 单独存为 GitHub Secrets
- **Keystore 原始文件同时备份到加密网盘（如 1Password / Vault），与 Git 仓库完全隔离**

### 注意事项

- Keystore 一旦丢失，只能重新签名发布新 App（旧用户无法通过覆盖安装更新），视同"换新 App"
- 不同构建环境（本地 / CI）必须使用同一个 Keystore，不能各自生成
- `minifyEnabled = true`（ProGuard 混淆）在 Release 构建中必须开启，注意为 Retrofit/Gson 数据模型与 Room 实体配置 keep rules，防止反射调用被混淆

---

## 六、多环境配置

Cam App 逻辑简单，需要区分环境的只有读学服务器的 API 地址（绑定、上传 URL 申请、帧元数据、心跳都走它）。OSS 地址由服务端在预签名 URL 中返回，不需要客户端配置。

| 环境 | 用途 | 构建方式 |
|------|------|---------|
| debug | 本地开发与测试，连本机 Docker 后端 | `assembleDebug`，传入本机地址 |
| release | 合并 `main` 后的正式版，连生产服务器 | `assembleRelease` |

通过 Android 的 **Build Variant** 机制在编译时注入不同的 `BuildConfig` 字段，不需要运行时配置文件，更安全。

---

## 七、版本号管理

| 字段 | 格式 | 管理方式 |
|------|------|---------|
| `versionCode` | 单调递增整数（如 `12`） | 由 CI 从 `BUILD_NUMBER` / Git Tag 自动生成，不手动维护 |
| `versionName` | 语义化版本（如 `1.2.0`） | 开发者手动更新到 `build.gradle.kts`，合并到 main 前更新 |

版本号规则：
- `patch`（1.0.**x**）：Bug 修复、抓拍与上传稳定性改进
- `minor`（1.**x**.0）：新增功能（如新增设置项、支持新硬件）
- `major`（**x**.0.0）：重大架构调整或与服务端协议不兼容的变更

---

## 八、注意事项汇总

| 事项 | 说明 |
|------|------|
| 安装来源限制 | 自托管 APK 需要用户手动开启"允许安装未知来源应用"，在用户引导文档中必须说明 |
| Android 13+ 权限变更 | 各 Android 版本的摄像头、后台启动权限有变化，发版前需在目标版本上回归测试 |
| ProGuard 混淆 | RootEncoder 库使用反射，需在 `proguard-rules.pro` 中添加 keep 规则，否则 Release 版本可能崩溃 |
| APK 覆盖安装 | 用户已安装旧版本时，新 APK 必须 `versionCode` 更大且签名一致，才能覆盖安装成功 |
| GitHub Actions 并发 | 多次快速 push 可能同时触发多个构建，建议配置 `concurrency` 取消旧构建，节省 Runner 时间 |
| SSH 部署密钥 | CI 上传 APK 到服务器需要 SSH 密钥，将部署专用 SSH 私钥存入 GitHub Secrets，服务器只授予写入 downloads 目录的最小权限 |

---

*文档版本 v1.0 | 对应项目 duxue-cam*
