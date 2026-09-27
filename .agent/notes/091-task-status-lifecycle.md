# Task 状态表补进计划设计

日期：2026-09-26

- 现象：未完成、已排在过去某天的任务，App 未排期列表能看到，但「安排到今天」被拒为未找到可修改的任务。
- 根因：`domain-planning.md` 没有 Task 状态迁移。`schedule_id` 一直指向旧日日程，新一天的可编辑集合不包含它；完成学习也不写 Task。
- 决策：Task 只设 `pool` / `scheduled` / `completed` / `cancelled`。本地日过后，未完成的 `scheduled` 由 `ReleaseUnfinishedTasks` 回到当天任务池，旧日程保留。`completed` 只由 Planning 消费 `StudySessionCompleted.v1` 写入。进行中和暂停仍属于 StudySession。
- 实现：确认计划写入 `scheduled`，移出当日计划回到 `pool`。处理当天安排和读取任务列表时释放已过本地日的未完成任务。`FinishStudySession` 不写 Task，同事务调用 `CompleteTask`。迁移 `20260926_21` 把旧的 `open`/`pending` 映射到 `pool`/`scheduled`。
