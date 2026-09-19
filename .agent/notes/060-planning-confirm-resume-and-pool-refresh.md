# Planning confirmation resume and task-pool refresh

> 日期：2026-09-17

## 现象与根因

- Planning Workflow 将 `save_draft()` 与 `interrupt()` 放在同一个 LangGraph node。resume 会重入 node，确认前又保存草稿，可能改变版本或覆盖已审阅内容。
- Coordinator 在分派前把 focus Run 标为 `active`，而 Adapter 原本只在 `waiting_for_ward` 时执行 `Command(resume=...)`。确认因此误走空输入分支，写入 `pending=["tasks"]` 草稿，正式日程没有落库；App 又无条件显示成功。
- Task 已在服务端登记后，Ward 首页没有重新查询 `assignments`，因此未排期任务列表仍是旧的本地快照。

## 规避

- 图拆为 `prepare_review`（唯一持久化草稿）与 `wait_for_confirmation`（只读已审阅 `draft_id` 后确认）；后者可安全 resume。
- `confirm_plan` 无条件使用 `Command(resume=...)`，绝不进入新图/空 `items` 分支。
- Ward 提交 Planning turn 后刷新首页投影；确认 UI 仅接受 `run_status=closed` 且 `interaction.status=confirmed`。
