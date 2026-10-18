# 128 — Guardian APK 由 GitHub Actions 签名打包

- `app-release.yml`：`main` 上 `duxue-app/**` 变更，或手动触发。先复用 `app-ci.yml`，再打签名 APK，挂 Actions Artifacts。
- 签名 Secret 在 `production`：`APP_KEYSTORE_BASE64`、`APP_KEYSTORE_PASSWORD`、`APP_KEY_ALIAS`、`APP_KEY_PASSWORD`。与 Cam 的钥匙分开。
- 包内 API 为公开地址 `https://duxuelai.xyz/api`，不读 `.env.prod`。
- 未设置 `KEYSTORE_FILE` 时，本地 release 仍用 debug 签名。
- iOS / Play AAB 仍不在这条流水线里。手动运行要等 workflow 进入 `main`。
