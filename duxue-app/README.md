# 读学 App

Flutter Guardian 客户端，已实现注册/登录与并发 JWT 刷新、Ward 管理、设备邀请码二维码、在线状态轮询、日报饼图与自绘时间轴。

```bash
flutter pub get
flutter run --dart-define=API_BASE_URL=http://192.168.1.2:8000
```

`APP_BASE_URL` 属于服务端运行环境，安装后的 App 无法读取它。构建发行包时，将同一个公开地址作为 Dart define 注入：

```bash
flutter build appbundle --release --dart-define=API_BASE_URL=https://api.example.com
```

仓库根目录的 `scripts/build-mobile-release.sh` 可从 `duxue-server/.env.prod` 读取**仅** `APP_BASE_URL` 并同时构建 Cam Android 包和 Guardian Android AAB。Codemagic 则在 `duxue_production` 环境组中配置同值的 `API_BASE_URL_PROD`。
