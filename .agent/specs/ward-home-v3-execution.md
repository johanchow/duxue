---
slug: ward-home-v3-execution
created: 2026-08-25T15:06:57Z
status: draft
---

# ward-home-v3-execution spec

## 做什么 / 为什么
按 `docs/mockups/ward-home-v3.html` 重构 Ward 首页：以「已确认的今日计划」「未进入今晚计划的任务池」和常驻计划协商对话为唯一信息层级。每个任务点击后须先确认才开始；进行中的任务点击后须先确认完成或暂停，保持 Ward 对学习节奏的自主决定权。

## 验收标准
- [x] Ward 首页与 v3 原型的信息层级和视觉一致：问候区、已确认计划时间轴、未入计划任务池、常驻 AI 计划协商入口，以及首页 / AI 伙伴 / 成长三 Tab。
- [x] 已确认计划项和未入计划任务项都可点按；点按后出现「确认开始」交互，未确认不创建或改变学习会话。
- [x] 已开始的任务显示进行中状态；再次点按后出现「确认完成」和「暂停」操作，取消不会改变状态；完成后任务不再可开始，暂停后可继续。
- [x] 计划协商对话只生成并展示未生效草稿；只有 Ward 明确确认草稿后才写入计划，任务池默认不自动进入今晚计划。
- [x] 任务的实际开始、暂停、完成状态可被可靠保存，并能在重启页面后恢复；AI 问答继续关联当前会话，且不展示实时专注判断。
- [x] 新增/更新 widget 与状态转换测试，`flutter analyze` 和 `flutter test` 通过。
- [x] Ward 首页与「今晚安排」弹层的麦克风支持按住说话；实时转写文本显示在弹层输入框，松开后保留为可编辑文本，且只有 Ward 后续确认计划时才会改变计划。
- [x] Ward 底部导航包含「我的」；仅显示当前关联 Guardian 名称，并可二次确认退出此设备绑定，不删除家庭关系或学习数据。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-app/lib/features/day_story_pages.dart`：将 Ward 首页重构为 v3 时间轴、任务池、计划协商 bottom sheet 与任务操作确认弹窗；把会话状态由仅内存变量提升为可恢复的页面数据。
  - `duxue-app/lib/features/day_story_pages.dart`：复用 Guardian 已验证的 `VoiceTranscriptionService`；为首页麦克风和弹层输入栏添加按住开始、松开提交、取消、60 秒保护、partial/final 回填和生命周期释放。
  - `duxue-server/app/main.py`、`duxue-app/lib/{core/api_client.dart,features/day_story_pages.dart}`：新增 Ward 自身资料读取接口，并实现“我的”Tab 与本机退出确认。
  - `duxue-app/lib/shared/app_ui.dart`（按需）：补充 v3 时间轴行、任务池行、确认操作 sheet 等可复用视觉组件，沿用现有主题令牌。
  - `duxue-app/lib/core/api_client.dart`、`duxue-app/lib/core/models.dart`：仅在后端契约确认后，封装计划外任务执行和会话暂停/恢复所需接口与模型。
  - `duxue-server/app/{main.py,models.py,schemas.py}`、迁移和测试（仅在获准扩展服务端时）：为 Assignment 创建可追踪会话、为 StudySession 保存暂停/恢复状态，使计划内与未入计划任务都能持久执行；保持 Ward 鉴权和 Guardian 不可替 Ward 开始/完成任务的边界。
  - `duxue-app/test/`、`.agent/notes/`：覆盖任务状态转换和确认交互，并沉淀数据模型与产品边界决定。
- 测试计划：先为状态转换写红测（待开始 → 确认开始 → 进行中 → 暂停/完成），并补 Ward 麦克风的 partial/final 回填与发送前不改计划测试；随后跑 `flutter analyze`、`flutter test`。若扩展服务端，同时跑对应 `pytest` 覆盖鉴权、计划内/计划外开始、暂停恢复、完成与重载恢复。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 落地 v3 首页布局与计划协商入口
- [x] 实现计划内与计划外任务的确认式开始/暂停/完成
- [x] 补齐测试、验证、笔记和 diff review
- [x] 接入 Ward 计划协商的实时语音输入并验证
- [x] 增加 Ward 我的页、Guardian 名称和本机退出绑定

## 备注
- 已确认的后端现状：`POST /plan-items/{item_id}/sessions` 只能以计划项开始学习；`POST /sessions/{id}/finish` 会直接把会话和计划项标为 completed，且没有暂停/恢复语义。`Assignment`（未入计划任务）没有可直接创建会话的接口。
- 因此“未入计划任务可以确认开始”与“进行中可以暂停后恢复并重载保持”不能仅靠 App 端真实完成。需要确认：允许本期一并最小扩展服务端持久化会话，还是 App 只提供本地临时状态（后者会丢失数据且不能进入报告，不建议）。
- 语音转写服务的 WebSocket 当前由服务端按 Guardian JWT 鉴权。Ward 登录同样持有 Ward JWT，但服务端尚未允许其连接该端点；需要将该 WebSocket 的认证扩展为 Guardian 或 Ward，仍保持百炼 Key 只在服务端。
