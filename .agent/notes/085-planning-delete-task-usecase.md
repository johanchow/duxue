# Planning 删除任务需要独立 Use Case

日期：2026-09-21

- 现象：规划 workflow 文档写了“说错了删除即可”，但 `PlanningAgentLoop` 只支持 `create/update/schedule/defer`，自然语言删除任务会被当成未知操作；HTTP 左滑删除也绕过了 PlanningDomainService。
- 根因：`remove_task_from_draft`、`defer_task` 和真正删除任务池 `Task` 的语义混在一起，缺少 `DeleteTask` 应用用例和 agent tool 契约。
- 规避：新增 `delete` operation，由服务端先在授权候选集中唯一解析目标，再检查任务状态和学习记录；未进入正式计划的任务可同事务删除 Task 并清理草稿引用。已进入正式计划的任务只写入 `proposed_task_deletions`，必须经过 DraftReview / ConfirmPlanDraft 二次确认后才真正删除。HTTP `DELETE /wards/{ward_id}/assignments/{assignment_id}` 复用 `PlanningDomainService.delete_task()`，并拒绝已入计划任务，避免绕过 workflow。
