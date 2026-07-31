# 读学Eye

原生 Android 抓拍端，包含一次性邀请码绑定、Keystore 加密凭证、CameraX 前台服务、Room 离线队列、指数退避补传、心跳、Wake/WiFi Lock，以及开机后由用户点击恢复的通知流程。

构建需要 JDK 17 与 Android SDK 35。可直接用 Android Studio 打开目录，或用本机 Gradle 执行 `gradle :app:assembleDebug -PapiBaseUrl=http://192.168.1.2:8000/`。
