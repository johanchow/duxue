# App 与账号

事实源：[design-app](../../docs/technical/design-app.md)、[prd-user](../../docs/product/prd-user.md)。design-app 里 Ward「计划 / AI」Tab 已过时：首页以本节为准。

## 目标

Guardian 用邮箱验证码注册和登录，不保存读学密码。Ward 使用可轮换的 refresh token。Ward 首页默认安静、对话按需展开，普通计划按需查看；仅主动 Sprint 展示限时卡，VoiceComposer 是唯一 AI 输入。

## 状态

- 已落地：邮箱验证码、Ward `POST /ward-auth/refresh`、安静首页与按需作业入口、通用错误文案、`main` 上 GitHub Actions 签名 APK。
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
- Guardian 当前首页为「报告 / 孩子 / 我的」：默认直接读所选孩子的报告，历史按日期查询；没有报告、整理中与加载失败分别呈现。作业传递仅在孩子页操作菜单，不再有常驻输入/录音或决策页。产品规则归 [首页 PRD §7.1](../../docs/product/prd-user.md#71-核心首页报告直接呈现)。
- 任务卡是读模型：安排状态来自 Task，进行中/暂停来自未结束 StudySession。见 [study.md](study.md)。
- APK：`duxue-app/**` 变更或手动触发。签名 Secret 在 `production` environment，与 Cam 钥匙分开。包内 API 为 `https://duxuelai.xyz/api`。

## 注意

- 共享语音和文字输入组件的拍照入口只显示相机图标，通过 Tooltip 保留「拍照」操作提示。
- 邮件接受不等于送达。不能按昵称或邮箱把微信账号自动合并。
- 未设 `KEYSTORE_FILE` 时本地 release 仍是 debug 签名。debug 覆盖安装不能代替正式渠道。

## 版本发布（2026-11-02）

- 已修复：APK workflow 曾写死 `--build-name=0.1.0`，覆盖 pubspec 版本名。回归测试直接执行 workflow 构建脚本，用替身 Flutter 验证版本来源、CI 构建号、文件名与 commit 注入；界面测试验证安装包版本读取与失败降级。
- 版本策略唯一归属：[部署文档 · App 版本管理](../../docs/deployment.md#app-版本管理)。Codemagic 双平台发布仍属规划，排查时先看实际 workflow。
- 验证：112 个 Flutter 测试、静态分析与 workflow YAML 校验通过；带 commit 注入的界面测试通过。Android debug APK 构建成功，aapt 确认版本名来自 pubspec、构建号被覆盖为测试值 42；正式签名流水线待合并后运行。

- 2026-11-03 Ward 首页目标已调整为 [PRD §六](../../docs/product/prd-user.md#六ward-首页与导航架构默认安静首页--按需对话--可选专注挑战) 的默认对话首页；普通当前/下一项不常驻，仅主动 Sprint 展示限时卡。旧任务池、常驻计时与结算布局已移除，当前待 Gate 2。

- 2026-11-03 本轮客户端已按新版首页完成改造，待 Gate 2：默认对话、作业详情按需打开、仅主动 Sprint 显示限时卡；取消旧横轨与虚构时间回退。任务与挑战命令确认后才更新状态，失败不伪称已暂停/开始。验证记录见[实现 spec](../specs/lightweight-planning-focus-sprint.md)。

- Guardian 报告页已实现，用户于2026-11-04确认本轮交付；事实源见 [首页 PRD](../../docs/product/prd-user.md#71-核心首页报告直接呈现)。`GuardianReportView` 共用于首页与旧报告/story路由；日报/凭证/展开原文独立读取，键含Ward/上海日期/题目。前台每分钟、恢复前台与下拉刷新更新；未知为空、失败可重试，不以自评为门禁。

- 2026-11-04 Guardian本轮验证：服务端770通过（1项既有网关测试跳过），Flutter124通过、静态分析无问题。用户确认后已归档spec；测试库已升至33，生产未迁移。历史日期、迟到响应、凭证独立重试及无数据不占位均有回归；真实设备长时间后台尚未人工验收。

- 2026-11-04 用户确认安静首页与ASR挑战方案后，本轮已实现待验收，见 [spec](../specs/ward-quiet-home-voice-sprint.md)。前述“默认对话”属于此前版本；最新产品规则归 [用户PRD §六](../../docs/product/prd-user.md#六ward-首页与导航架构默认安静首页--按需对话--可选专注挑战)。
- 底部VoiceComposer结构与录音/拍照逻辑未变，宿主按需分派。相机选好图才打开对话，取消保持安静；收起后保存Thread/草稿/在途回复，不被迟到结果重开。
- 挑战口述使用独立预览，草稿只保存在本轮；取消/重开/改说使旧预览失效。ASR在录音预检时绑定模式与代次，取消后的final不能误发普通聊天。确认创建失败重试保持command_id，活跃挑战恢复不重复开始。

- 本轮自动化验证：服务端776通过（1项既有网关二进制测试跳过）、Flutter137通过、静态分析无问题；7条真实模型口述样例通过。验收记录保留在进行中spec，尚未部署，无新迁移。

- 2026-11-04 用户要求先切换分支后本地提交，本轮分支为 `feat/ward-quiet-home-voice-sprint`；保留验收spec，未授权push。
