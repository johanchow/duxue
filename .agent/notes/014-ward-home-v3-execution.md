# Ward 首页 v3：跨计划执行状态

- Ward 首页只将已确认的 `PlanItem` 呈现在时间轴中；仍为 `open`、但已被计划引用的 `Assignment` 会依据 `assignment_id` 从任务池排除，避免重复显示。
- `StudySession` 现在可关联 `plan_item_id` 或 `assignment_id`：前者服务已确认计划，后者支持 Ward 从任务池确认开始，不会把任务静默加入计划。任务只能由 Ward token 启动、暂停、恢复和完成。
- 暂停将累计秒数写入会话，重载计划/任务池接口会返回其 active 或 paused 会话，App 据此恢复进行中状态；完成状态从任务池移除或在计划时间轴上显示完成。
- 暂停/完成都必须二次确认；界面不展示实时专注、分心或行为评分。计划协商入口当前保留未生效草稿说明，确认后才沿用现有保存并确认计划 API。
- 验证：`duxue-app` 的 `flutter analyze`、10 项 `flutter test`，以及 `duxue-server` 的 25 项 `.venv/bin/pytest tests -v` 均通过（2026-08-25）。
- `VoiceComposer` 将「可选媒体上传 / 多行文本 / 长按语音 / 发送」封装为单一可复用组件。Ward 计划协商已采用它；Guardian 现有输入栏保留原已验证实现，可在后续视觉整理时无行为风险地替换为该组件。
- ASR WebSocket 改用 `current_guardian_or_ward` 认证，因此 Ward JWT 可安全复用既有服务端语音代理；百炼 Key 仍只存在服务端。
- Ward “我的”页通过仅限 `current_ward` 的 `/ward/profile` 获取关联 Guardian 名称。退出绑定只清理本机 access token、Ward ID 与 refresh token，绝不允许 Ward 端删除 `guardian_ward_relations` 或学习数据。
