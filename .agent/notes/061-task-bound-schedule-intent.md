# Task-bound schedule intent

> 日期：2026-09-17

## 决策

- `start_at` 不是孤立字段；它必须属于唯一 `assignment_id`。同一候选时间被模型写到多个 Task 时，服务端清空这些槽、标记 `ambiguous_target_task`，并在 DraftReview 前澄清。
- `after_assignment_id` / `before_assignment_id` 仅引用当前 Ward 的任务。确定性服务在锚点时间槽已知时推导相邻任务的时间；无法解析的引用和循环不生成猜测性时间槽。
- `plan_draft_view` 在草稿展示阶段计算重叠并关闭确认按钮；确认事务仍会复核，作为并发与陈旧草稿的最终防线。
- 设计真相更新于 `docs/technical/domain-planning.md v1.2`，包含意图字段、不变量、交互结果、UML 时序和验收场景。

## 澄清批次（v1.3）

- 单一 active 的单位是 `ClarificationBatch`，不是 `ClarificationSlot`。一个 Batch 可以一次请求多个任务的时长或时间信息。
- 文本批量回答只有目标明确（逐项名称）或量词明确（“都/各”）时才能原子写入；多个 pending Slot 下的孤立数值必须再次消歧。
- `structured_form` 必须回传每个 Slot 的 `slot_id`，避免 Agent 重新猜测归属。
