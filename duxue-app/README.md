# 读学 App

Flutter Guardian 客户端，已实现注册/登录与并发 JWT 刷新、Ward 管理、设备邀请码二维码、在线状态轮询、日报饼图与自绘时间轴。

```bash
flutter pub get
flutter run --dart-define=API_BASE_URL=http://192.168.1.2:8000
```

## 本地调试与遥测

复制 `config/dart-defines.local.example.json` 为
`config/dart-defines.local.json`，按当前运行目标修改 `API_BASE_URL` 后运行：

```bash
flutter run --dart-define-from-file=config/dart-defines.local.json
```

该文件只保存公开地址、遥测开关和采样率；不允许填入 Grafana token、OTLP
Authorization 或任何用户资料。App telemetry 通过登录后的 Bearer token 发给
Server relay，再由 Server 使用其私有 OTLP 凭据导出。若只想做普通本地调试，继续
使用上面的单个 `API_BASE_URL` 命令即可，遥测默认关闭。

`127.0.0.1` 适用于桌面、iOS 模拟器；Android 模拟器改为 `10.0.2.2`。

Android 真机用 USB 调试、本机服务端在 `8000` 时，在 `duxue-app` 目录执行：

```bash
adb reverse tcp:8000 tcp:8000 && flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

`adb reverse` 把手机的 `8000` 转到电脑上的服务端。USB 重新连接后需要再执行一次。手机和电脑在同一 Wi-Fi 时，也可以把 `API_BASE_URL` 换成开发机的局域网 IP。

`APP_BASE_URL` 属于服务端运行环境，安装后的 App 无法读取它。构建发行包时，将同一个公开地址作为 Dart define 注入：

```bash
flutter build appbundle --release --dart-define=API_BASE_URL=https://api.example.com
```

仓库根目录的 `scripts/build-mobile-release.sh` 可从 `duxue-server/.env.prod` 读取**仅** `APP_BASE_URL` 并同时构建 Cam Android 包和 Guardian Android AAB。Codemagic 则在 `duxue_production` 环境组中配置同值的 `API_BASE_URL_PROD`。
