# 计划域：任务创建与入计划分离

> 日期：2026-09-16

## 决策

`Task` 与 `DailySchedule` 不是同一件事。

- **创建任务**：条件是 `title` + `planned_minutes`。立即 `RegisterTask`，**不经过 Ward 确认**；说错了删除即可。
- **进入计划**：确认屏列出**全部未完成任务**，每项展示耗时、开始、结束。Ward 确认后，只有时间槽完整且无冲突的项才 `mark_scheduled()`；没填开始/结束的仍留在任务池。


上一版把 `new_task` 放到确认时创建，把任务内容与安排绑死了，已从 `domain-planning.md` 时序图和不变量中拆开。
