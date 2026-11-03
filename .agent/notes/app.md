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
- 首页精简说明：移除问候区「你先说，我来帮你记录和检查安排」与任务池底部的重复排期/删除说明，并删除随文案占用的间距；任务池标题保留数量与左滑删除提示。
- Guardian 孩子首页左上角统一为「全部孩子」，移除「我的家庭」副标题及列表内「我的孩子」标题。有孩子时底部固定显示 AppCard + InputModeComposer，默认语音模式复用 Ward 的 VoiceComposer，文案「传递作业或留言」；左侧图标表示将要切换的模式（键盘 / 麦克风），文字模式支持输入、发送和拍照，切换保留文字草稿。轻点或发送后进入原传递面板，语音/文字带入可编辑内容，拍照同时带入文字草稿与附件。列表独立滚动，无孩子时继续优先引导创建档案。
- 任务卡是读模型：安排状态来自 Task，进行中/暂停来自未结束 StudySession。见 [study.md](study.md)。
- APK：`duxue-app/**` 变更或手动触发。签名 Secret 在 `production` environment，与 Cam 钥匙分开。包内 API 为 `https://duxuelai.xyz/api`。

## 注意

- Guardian 输入模式切换按钮使用 32×44 占位、22 图标与 4 间距，避免默认 IconButton 留白挤占输入区。
- 共享语音和文字输入组件的拍照入口只显示相机图标，通过 Tooltip 保留「拍照」操作提示。
- 邮件接受不等于送达。不能按昵称或邮箱把微信账号自动合并。
- 未设 `KEYSTORE_FILE` 时本地 release 仍是 debug 签名。debug 覆盖安装不能代替正式渠道。

## 版本发布（2026-11-02）

- 已修复：APK workflow 曾写死 `--build-name=0.1.0`，覆盖 pubspec 版本名。回归测试直接执行 workflow 构建脚本，用替身 Flutter 验证版本来源、CI 构建号、文件名与 commit 注入；界面测试验证安装包版本读取与失败降级。
- 版本策略唯一归属：[部署文档 · App 版本管理](../../docs/deployment.md#app-版本管理)。Codemagic 双平台发布仍属规划，排查时先看实际 workflow。
- 验证：112 个 Flutter 测试、静态分析与 workflow YAML 校验通过；带 commit 注入的界面测试通过。Android debug APK 构建成功，aapt 确认版本名来自 pubspec、构建号被覆盖为测试值 42；正式签名流水线待合并后运行。
