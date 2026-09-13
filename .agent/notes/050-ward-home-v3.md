# Ward 首页 V3：AI Native 统一入口

> 日期：2026-09-13  
> 关联规范：`.agent/specs/ward-home-v3.md`

## 决策

- `WardDayPage` 首页遵循 `docs/mockups/ward-home-v3.html`：已确认计划是供学生浏览和 AI 理解的上下文轨，不再是首页主导的纵向任务清单。
- VoiceComposer 仍是唯一的 AI 输入入口。页面只调整传入文案和回调编排，未修改 `shared/voice_composer.dart`。
- 首页右上角不放 AI 快捷入口，底部导航也不放“AI 伙伴”Tab；避免与 VoiceComposer 的唯一入口语义冲突。
- 对话 overlay 必须低于首页的 VoiceComposer dock：主页 Stack 先绘制 overlay、再绘制 dock；完整计划 sheet 则会临时隐藏 dock。`VoiceComposer.onTap` 是可选、业务无关的转发 prop，Ward 首页用它打开对话；录音保持长按手势。
- 计划芯片、AI 图标和 VoiceComposer 语音结果统一进入首页内的对话浮层；该层保留既有 plan intake API 产生的反馈、草稿和显式确认操作，保证 Ward 决策权不变。
- “待你决定”的左滑删除只写入页面 state 的 `removedPoolTaskIds`，不调用或假设不存在的服务端删除任务 API；点按任务仍保留既有“开始学习？”确认流程。
- ASR WebSocket 改为先完成握手、再执行鉴权。鉴权失败向客户端回传通用 `unauthorized` 错误后关闭；服务端日志和 `duxue.asr.sessions` 指标只记录阶段、结果、角色与认证头是否存在/认证 scheme，绝不记录 JWT、音频或转写文本。客户端将连接、鉴权、服务端和 socket 错误分类上报为已有的 `app.asr.session` 遥测。
- Ward 会话使用独立的、轮换式 refresh token，并将它绑定至 `WardCredential.session_version`。再次绑定会撤销旧 refresh token，因此换机后旧设备无法通过 refresh 取得新 access token。App 的启动恢复、Dio 401 重试和语音开始前预检均走 `ApiClient` 的同一刷新实现；刷新失败清空安全存储并驱动路由回到绑定入口。

## 验证

- `flutter test test/app_ui_test.dart`：5 passed，覆盖既有任务启动、V3 计划轨/语境、任务池本地删除及 VoiceComposer 交互。
- `flutter analyze`：No issues found。
- `duxue-server/.venv/bin/pytest tests -q`：123 passed（2 个既有 FastAPI `on_event` deprecation warnings）。
- `ENV_FILE=.env .venv/bin/alembic upgrade head && ... alembic check`：已升级到 `20260913_16`，schema 无待生成变更。
- Ward 会话续期后的 `flutter test`、`flutter analyze`：全绿；服务端 `pytest tests -q`：123 passed（同上两项既有 warning）。
