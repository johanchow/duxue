---
slug: ward-home-v3
created: 2026-09-13T01:14:06Z
status: draft
---

# ward-home-v3 spec

## 做什么 / 为什么
将 Ward 学生首页按照 `docs/mockups/ward-home-v3.html` 重构为 AI Native 的统一对话入口：已确认计划仅作为 AI 可感知的上下文预览，待决定项为本地操作，VoiceComposer 是页面唯一 AI 输入入口；不修改 VoiceComposer 本身实现。

## 验收标准
- [x] 首页以问候、计划横向上下文轨和“待你决定”任务池呈现；计划可打开完整时间轴，计划任务可进入带相应语境的 AI 对话。
- [x] 首页的 AI 浮层包含当前已确认计划/任务池摘要、会话消息、AI 反馈和待确认计划草稿；确认草稿仍调用既有计划 intake API 并刷新首页。
- [x] 首页底部继续直接复用 `VoiceComposer`，不改动该组件；语音转写或图片上传会打开/更新上述 AI 对话；无文字输入入口，首页右上角无 AI 快捷入口，底部导航无“AI 伙伴”Tab。
- [x] 待决定任务支持本地左滑删除（并仅在 UI 本地移除），原有“开始学习”确认流程仍可由点击任务触发。
- [x] 加载、空计划、空任务池、API 失败和已有会话等状态不崩溃；现有相关 widget 测试及新增交互测试通过，`flutter analyze` 无新增问题。
- [x] ASR WebSocket 鉴权失败会以脱敏的结构化服务端日志、低基数指标和客户端遥测分类记录；客户端可得到可行动的登录提示而非握手异常。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-app/lib/features/day_story_pages.dart`：仅重构 `WardDayPage` 的首页布局与其局部状态；保留现有加载、任务启动/暂停/完成、计划 intake、图片上传和导航逻辑。
  - `duxue-app/test/app_ui_test.dart`：保留 VoiceComposer 覆盖，并补首页 V3 的计划展开、语音触发对话/草稿确认、任务池本地删除等覆盖。
  - `.agent/notes/050-ward-home-v3.md`：记录原型到实现的关键决策及行为边界。
- 实现步骤：
  1. 提取首页需要的显示模型/辅助方法，依据当前计划、任务和个人资料计算问候、计划轨、任务池、当前上下文摘要与本地删除集合。
  2. 将首页改成带悬浮 VoiceComposer dock 的 Stack，并实现计划完整时间轴 sheet、AI 对话 sheet、计划芯片/AI 圆点的入口、加载与空状态。
  3. 把既有 VoiceComposer 的语音和图片回调接入对话状态；保留 API 调用与确认计划逻辑，将反馈和草稿放入对话层。
  4. 为任务池增加 `Dismissible` 本地删除，并保留点按任务后的既有学习确认操作。
  5. 补 widget 测试，执行 formatter、相关测试、`flutter analyze`，检查 diff，并将实现决策沉淀至笔记。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 实现 V3 首页、计划列表与 AI 对话层
- [x] 接入既有 VoiceComposer 与计划 intake
- [x] 实现任务池本地左滑删除
- [x] 补充并通过 widget 测试
- [x] 执行格式化、静态检查、diff review
- [x] 写入决策笔记

## 备注
- 设计依据：`docs/mockups/ward-home-v3.html`。
- 保持学生的计划决策权：AI 只整理、检查冲突并产出草稿，最终必须由 Ward 明确确认。
- mockup 中“待你决定”删除是原型内的本地轻操作；本次不新增删除任务的服务端 API。
