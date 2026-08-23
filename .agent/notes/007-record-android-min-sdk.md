# record_android 最低 Android 版本

- 现象：加入实时语音输入的 `record 6.2.1` 后，Android Debug 构建提示 `record_android` 要求 `minSdkVersion 23`。
- 根因：App 的 `minSdk` 继承 Flutter 默认值（API 21），低于录音插件当前 Android 实现的最低版本。
- 处理：在 `duxue-app/android/app/build.gradle.kts` 显式设为 `minSdk = 23`。这会停止支持 Android 5.0–5.1（API 21–22），但满足语音录制所需平台能力；后续升级录音插件时应重新执行 Android Debug 构建确认要求。
- 构建继续暴露的兼容项：`flutter_secure_storage`、`path_provider_android` 和 `record_android` 均要求 NDK `27.0.12077973`，因此也将 App 的 `ndkVersion` 固定到该版本；Android NDK 在该升级路径上向后兼容。
