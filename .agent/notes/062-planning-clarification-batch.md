# Planning clarification batch

日期：2026-09-18

- `PlanDraft.working_state.active_clarification_batch` 是时长追问的唯一持久化归属；每个 slot 都有稳定 `slot_id` 和明确的既有 Task 或新任务候选目标。
- Planning adapter 在调用 intake 模型前先解析 active batch：按任务名的多项回复、或“都/各 N 分钟”可批量写入；多 slot 下仅有裸时长不会写入任何任务，而是再次澄清。
- 所有 slot 解决后，新候选才登记为 Task 并进入任务池。batch 绑定 `issued_draft_version`，旧回复不能改写新草稿。
