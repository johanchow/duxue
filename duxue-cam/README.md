# 读学Eye

原生 Android 抓拍端，包含一次性邀请码绑定、Keystore 加密凭证、CameraX 前台服务、Room 离线队列、指数退避补传、心跳、Wake/WiFi Lock，以及开机后由用户点击恢复的通知流程。

构建需要 JDK 17 与 Android SDK 35。可直接用 Android Studio 打开目录，或用本机 Gradle 执行 `gradle :app:assembleDebug -PapiBaseUrl=http://192.168.1.2:8000/`。

生产构建通过 Gradle property 或环境变量注入公开 API 地址：`gradle :app:assembleRelease -PapiBaseUrl=https://api.example.com`。不要把服务端 `.env.prod` 或任何数据库、OSS、Redis 凭证打进 APK。

Cam 相关改动合并至 `main` 后自动构建并更新正式下载包；`cam-v*` Tag 额外创建可回退的 GitHub Release。签名和下载站部署所需 Secret 见仓库根目录的 [部署说明](../docs/deployment.md)。
