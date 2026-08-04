# 读学App（Guardian App）— CI/CD 方案

> 版本 v1.0 | 平台：iOS + Android（Flutter）

---

## 一、方案选择：Codemagic

### 为什么选 Codemagic

Guardian App 是 Flutter 双平台项目，CI/CD 工具的核心挑战在于**同时构建 iOS（需要 macOS 环境）和 Android**。各方案对比如下：

| 工具 | Flutter 支持 | iOS 构建 | 费用 | 配置复杂度 |
|------|------------|---------|------|----------|
| **Codemagic** | ✅ 原生 Flutter 专属 | ✅ 内置 macOS | 免费 500min/月；$95/月起 | 低 |
| GitHub Actions | ✅ 需手动配置 | ✅ macOS runner | macOS runner $0.08/min | 高 |
| Fastlane | ✅ 需配合其他 Runner | ✅ 需 macOS 机器 | 开源免费，但要自维护 Runner | 高 |
| Bitrise | ✅ 支持 | ✅ 支持 | $36/月起，免费额度少 | 中 |

**选择 Codemagic 的核心原因：**

1. **Flutter 原生支持**：理解 `pubspec.yaml`、`build_runner`、`flutter test`、多平台构建，无需额外适配
2. **内置 macOS 环境**：iOS 构建必须在 macOS 上执行，Codemagic 直接提供，无需自购 Mac Mini 作为构建机
3. **App Store Connect 直连**：通过 API Key 直接将 IPA 提交到 TestFlight，全程自动化
4. **Google Play 直连**：支持直接发布到 internal / alpha / beta / production 轨道
5. **免费额度够用早期**：500 分钟/月对于小频率发布完全足够，团队规模扩大再升级

---

## 二、接入准备（从零到跑通 CI 的完整步骤）

Codemagic 的配置分为两部分：**仓库内的配置文件**（`codemagic.yaml`）和**Codemagic 控制台的密钥托管**。两者缺一不可。

### 第一步：注册 Codemagic 账号并连接代码仓库

1. 访问 [codemagic.io](https://codemagic.io) 注册账号
2. 在控制台点击 **Add application** → 选择 GitHub → 授权访问 → 选择 `duxue-app` 仓库
3. 选择配置方式为 **codemagic.yaml**（而非 UI 向导，yaml 可版本管理）

### 第二步：创建 codemagic.yaml 配置文件

Codemagic 读取仓库根目录的 `codemagic.yaml`。当前项目是 monorepo，因此该文件应位于 `duxue/codemagic.yaml`，而不是 `duxue-app/` 子目录：

```
duxue/
└── codemagic.yaml    # Codemagic 读取此文件作为流水线定义
```

此文件提交到 Git，Codemagic 每次构建时自动读取最新版本。注意：当前尚未提交 `duxue-app/android` 与 `duxue-app/ios` 工程，生成并提交它们前无法产出可签名的 AAB/IPA，详见 [`docs/deployment.md`](../../docs/deployment.md)。

### 第三步：生成并托管 Android Keystore

与 Cam App 相同，先在本地生成 Keystore：

```bash
keytool -genkeypair \
  -alias duxue-app \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -keystore duxue-app.keystore
```

然后在 Codemagic 控制台托管：
- 进入 **Teams → Code signing identities → Android keystores**
- 上传 `duxue-app.keystore` 文件
- Codemagic 会生成一个引用 ID，在 `codemagic.yaml` 中通过该 ID 引用，不需要在文件中写明文密码

### 第四步：配置 iOS 签名（需要 Apple Developer 账号）

iOS 签名是整个流程中最复杂的部分，需要提前完成以下准备：

**4.1 Apple Developer 账号（前置条件）**
- 注册地址：[developer.apple.com](https://developer.apple.com)
- 费用：$99/年，审核约 1~2 个工作日
- 需要有效的企业或个人信息，国内注册需要支持国际支付的信用卡

**4.2 在 App Store Connect 创建 App 记录**
- 登录 [appstoreconnect.apple.com](https://appstoreconnect.apple.com)
- 新建 App → 填写名称、Bundle ID（如 `com.duxue.app`）、SKU
- Bundle ID 必须与 Xcode 工程中的设置完全一致

**4.3 生成 App Store Connect API Key**
- 在 App Store Connect → **Users and Access → Integrations → App Store Connect API**
- 创建 API Key，权限选择 **App Manager**
- 下载 `.p8` 文件（**只能下载一次，丢失无法重新下载**）
- 记录 Key ID 和 Issuer ID

**4.4 在 Codemagic 上托管 iOS 证书**
- 进入 **Teams → Code signing identities → iOS certificates**
- 方式一（推荐）：填入 App Store Connect API Key，Codemagic 自动从 Apple 拉取和管理证书
- 方式二：手动上传 Distribution 证书（`.p12`）和 Provisioning Profile

### 第五步：配置 Google Play 自动发布（可选）

如果需要 CI 直接推包到 Google Play：

1. 在 Google Play Console → **Setup → API access** → 关联 Google Cloud 项目
2. 在 Google Cloud Console 创建 **Service Account**，授予 Google Play 的 **Release Manager** 角色
3. 下载 Service Account 的 JSON 密钥文件
4. 在 Codemagic 控制台 → **Environment variables** → 添加 `GCLOUD_SERVICE_ACCOUNT_CREDENTIALS`（文件类型），上传 JSON 文件

### 第六步：在 Codemagic 配置环境变量

进入 **Codemagic 控制台 → 对应应用 → Environment variables**，添加以下变量：

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `API_BASE_URL_STAGING` | String（加密） | Staging 环境 API 地址 |
| `API_BASE_URL_PROD` | String（加密） | 生产环境 API 地址 |
| `APP_STORE_CONNECT_KEY_IDENTIFIER` | String | Apple API Key 的 Key ID |
| `APP_STORE_CONNECT_ISSUER_ID` | String | Apple API Key 的 Issuer ID |
| `APP_STORE_CONNECT_PRIVATE_KEY` | File（加密） | 上传 `.p8` 文件 |
| `GCLOUD_SERVICE_ACCOUNT_CREDENTIALS` | File（加密） | Google Play Service Account JSON |

### 第七步：验证流水线

1. 向 `main` 分支提交一个空白 commit，触发 Codemagic 构建
2. 在 Codemagic 控制台查看构建日志，确认各阶段通过
3. 检查 TestFlight 后台是否收到新的 Build（iOS）
4. 检查 Google Play Console Internal Track 是否有新版本（Android）
5. 从 TestFlight 安装到 iPhone 真机验证功能正常

---

## 三、流水线设计

### 触发策略

| 分支 / 事件 | 触发动作 | 说明 |
|------------|---------|------|
| `main` 分支 push | 自动构建 + 发布 TestFlight + Android Internal Track | 每次合并主干自动推测试版 |
| Tag `v*`（如 `v1.2.0`） | 自动构建 + 提交 App Store 审核 + Google Play Production | 正式版发布 |
| PR 提交 | 只跑测试，不构建产物 | 保证合并前测试通过 |

### 流水线阶段

```
代码提交
  └─ 阶段一：质量门禁
       ├─ flutter pub get
       ├─ flutter analyze（静态检查）
       └─ flutter test（单元测试 + Widget 测试）

  └─ 阶段二：Android 构建（并行）
       ├─ build_runner 代码生成（freezed / json_serializable）
       ├─ flutter build appbundle --release（Google Play 用 AAB）
       ├─ flutter build apk --release（国内商店用 APK）
       └─ 签名（Keystore 从 Codemagic 密钥管理注入）

  └─ 阶段三：iOS 构建（并行）
       ├─ flutter build ipa --release
       ├─ 签名（证书 + Provisioning Profile 从 Codemagic 管理）
       └─ 上传 IPA

  └─ 阶段四：发布
       ├─ Android → Google Play Internal Track
       ├─ Android APK → 国内商店（手动或脚本上传）
       └─ iOS → TestFlight（自动）/ App Store（Tag 触发时）
```

---

## 四、证书与密钥管理

这是 CI/CD 中最容易出问题的环节，需要严格管理。

### Android 签名

- Keystore 文件加密后存入 Codemagic 的 **Environment Variables（File 类型）**，构建时自动注入，不提交到 Git
- `KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD` 均作为加密环境变量存储
- Google Play 发布使用 **Google Service Account JSON**（在 Google Play Console 创建），同样存为加密变量

### iOS 签名

- 使用 Codemagic 的 **Code Signing Identities** 功能托管证书（`.p12`）和 Provisioning Profile
- 不需要手动配置 `Xcode` 签名，Codemagic 自动处理 `match` / `fastlane` 等签名流程
- App Store Connect API Key（`AuthKey_xxx.p8`）存为加密文件变量，用于无需人工登录的自动提交

### 注意事项

- Apple 开发者证书有效期 **1 年**，过期前 Codemagic 会发邮件提醒，需提前续期
- Distribution 证书和 Development 证书是两套，CI/CD 使用 Distribution 证书
- 不同 Bundle ID 对应不同 App ID，上架前必须在 App Store Connect 创建 App 记录

---

## 五、多环境配置

App 需要区分开发、测试、生产三个环境，通过 `--dart-define` 注入环境变量，不在代码中硬编写 API 地址。

| 环境 | API 地址来源 | 发布渠道 |
|------|------------|---------|
| dev | 本地 Docker（localhost） | 开发者本机 run |
| staging | staging 服务器 | TestFlight / Android Internal |
| production | 生产服务器 | App Store / Google Play Production |

Codemagic 的不同 workflow 分别注入对应的 `API_BASE_URL` 环境变量，构建产物与环境严格对应，不会出现"测试版 App 打到生产环境"的问题。

---

## 六、版本号管理

- 版本格式遵循 `pubspec.yaml` 的 `version: 1.2.0+12`（`版本名+构建号`）
- **构建号**（`+12` 部分）由 Codemagic 自动从 `BUILD_NUMBER` 环境变量注入，每次构建单调递增
- **版本名**（`1.2.0` 部分）由开发者手动更新到 `pubspec.yaml`，遵循语义化版本

---

## 七、国内 Android 应用商店发布

Google Play 可以通过 Codemagic 全自动发布，但华为、小米等国内商店目前没有标准化的 API 对接方案，需要**手动上传 APK**。

建议的做法：
- CI/CD 自动构建 APK 并上传到固定 OSS 目录（或 GitHub Release Artifacts）
- 发版时由运营/开发人员手动登录各商店开发者后台上传
- 发版频率低（通常 2~4 周一次），手动操作成本可接受

**国内商店上架的前置条件（与 CI/CD 无关，但影响发版节奏）：**

| 要求 | 说明 | 准备周期 |
|------|------|---------|
| 软件著作权 | 华为、小米等均要求提供 | 约 1~3 个月，需尽早申请 |
| 营业执照 | 企业开发者账号必须 | 视情况而定 |
| App 隐私政策 URL | 所有商店强制要求 | 上架前准备好 |
| 应用备案 | 工信部要求 | 约 2~4 周 |

---

## 八、注意事项汇总

| 事项 | 说明 |
|------|------|
| Apple 审核周期 | 首次上架约 1~3 天；更新一般 24 小时内；节假日可能更长，发版计划需预留时间 |
| TestFlight 外部测试员 | 首次需要 Apple 审核（约 1~2 天），之后每个 Build 自动推送给已邀请的测试员 |
| iOS 证书过期 | 每年续期，过期后 CI/CD 构建失败，需提前 30 天处理 |
| Android 签名一致性 | 签名后的 App 更新必须使用完全相同的 Keystore，Keystore 丢失将无法更新已上架 App |
| build_runner 时间 | freezed / json_serializable 代码生成在 CI 上可能耗时 2~5 分钟，属正常范围 |
| Codemagic 免费额度 | 500 分钟/月，iOS + Android 双端一次完整构建约 15~25 分钟，每月约可构建 20~30 次 |

---

*文档版本 v1.0 | 对应项目 duxue-app*
