# Companion/Planning 协议对齐

> 日期：2026-09-16

## 实现决策

- `PlanningDomainService.register_tasks()` 会在解析结果有 `title + planned_minutes` 时先把新任务写入池；草稿随后只保留已有 `assignment_id`。缺时长只进入澄清状态，不创建虚假的草稿任务。
- `PlanDraft.items` 的 `start_at` 为 Ward 明示值，`end_at` 由时长确定性计算。确认只安排存在完整时间槽且无冲突的项；没有时间槽的未完成任务仍显示在草稿 Query 中。
- `plan_confirm_list` 只传 `object_ref`，App 再调用 Ward 授权的 `/companion/planning/drafts/{id}` 读取最新列表。新 App 不读取 `interaction.items`，也不发送 `planning_confirm`。
- 可执行 `confirm_plan` action 的 ID 由 Planning Outcome 签发并存入 `AgentRun.outcome`。后续命令必须匹配该 ID、当前 run/attempt、草稿版本和 Thread 版本，过期卡片返回 `409`。
- 为避免 LangGraph 在 interrupt resume 时把未变草稿误增版本，`save_draft()` 仅在内容、待补字段或状态实际变化时递增草稿版本。

## 2026-09-17 回归修复

- LangGraph 会重新执行含 `interrupt()` 的节点；因此 `prepare_review`（唯一调用 `save_draft()` 的节点）与 `wait_for_confirmation` 分开。确认 resume 只读取 `draft_id` 并调用 `confirm()`，绝不能写回草稿。
- 新任务已经登记但尚无可用时间槽时，Planning Outcome 使用 `clarify`，明确告知「已添加任务」，并邀请 Ward 说明开始时间或前后顺序；任务已入池但不自动入正式日程。
- App 只在 `run_status=closed` 且 `interaction.status=confirmed` 时清空草稿、刷新首页并提示成功；其它结果保留草稿并显示失败，避免 UI 假报确认。
