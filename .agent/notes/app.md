# App 与账号

事实源：[design-app](../../docs/technical/design-app.md)、[prd-user](../../docs/product/prd-user.md)。design-app 里 Ward「计划 / AI」Tab 已过时：首页以本节为准。

## 目标

Guardian 用邮箱验证码注册和登录，不保存读学密码。Ward 使用可轮换的 refresh token。Ward 首页以计划为上下文，VoiceComposer 是唯一 AI 输入。

## 状态

- 已落地：邮箱验证码、Ward `POST /ward-auth/refresh`、首页横轨计划、通用错误文案、`main` 上 GitHub Actions 签名 APK。
- 未做：微信登录。iOS / Play AAB 不在 APK 流水线。
- 首页左滑删除走服务端，不是只改本地 state。

## 决策

- 验证码 6 位、只存 HMAC、10 分钟、单次使用。重发使旧码失效。同邮箱发送用 PostgreSQL advisory lock。发送失败回滚并返回 503，不回显服务商错误。
- 未注册邮箱登录返回 404 `account not found` 时事务回滚，原码仍可注册。再次发码后必须用新码。App 只对这一条 404 提示「该邮箱尚未注册」。
- 重发成功清空输入框。发信失败保留原码。登录/注册错误放在表单内并收起键盘。
- 用户可见错误走 `core/user_error_message.dart`，不展示 URL、响应体或异常字符串。
- refresh 绑定 `WardCredential.session_version`。再次绑定撤销旧 refresh。只在 refresh 请求本身失败时清会话。刷新成功但原请求仍 401 时保留新凭证。
- 首页无右上角 AI 入口，无「AI 伙伴」Tab。对话层低于底部 composer。完整计划 sheet 临时隐藏 dock。不改 `VoiceComposer` 的既有交互。
- 任务卡是读模型：安排状态来自 Task，进行中/暂停来自未结束 StudySession。见 [study.md](study.md)。
- APK：`duxue-app/**` 变更或手动触发。签名 Secret 在 `production` environment，与 Cam 钥匙分开。包内 API 为 `https://duxuelai.xyz/api`。

## 注意

- 邮件接受不等于送达。不能按昵称或邮箱把微信账号自动合并。
- 未设 `KEYSTORE_FILE` 时本地 release 仍是 debug 签名。debug 覆盖安装不能代替正式渠道。
