# 跨天未完成任务重置为未排期未进行，且新答疑线程不继承遗留 open 题目

日期：2026-10-15

- 现象：
  1. 用户在新的一天发起与作业无关的提问（「为我说明一下地球和太阳的区别」「来一些更全面详细对比」），即使今日没有确认计划，第 1 轮末尾仍被拼上「先回到正在进行的任务，这个问题可以稍后再问。」，第 2 轮模型直接返回 `act=redirect`（「但我们先把注意力放回手头的任务上吧」）。
  2. 首页左滑删除「英语的典范故事阅读」后，卡片短暂消失又自动弹回列表。
- 根因：
  1. `ReleaseUnfinishedTasks` 跨天时只将 `Task.status` 重置为 `pool`，未关闭往日遗留的 `active`/`paused` `StudySession`（9 月 27 日暂停的会话一直留存）。`TutoringWorkflow._find_session` 未传 `study_session_id` 时捞出该旧会话，导致 `task_active=True` 并复用同一 `TutoringSession` 下前几日残留的 `open` `TutoringProblem`（`permit.answer_protected=true`）。
  2. 左滑删除调用 `DELETE /wards/{ward_id}/assignments/{assignment_id}` 时，`delete_task` 因该任务挂着上述往日未结束的 `StudySession` 返回 `409 已有学习记录的任务不能删除`，前端捕获异常后将卡片恢复。
- 规避：
  1. `PlanningDomainService.release_unfinished_tasks` 跨天释放时，同步将往日未结束（`active`/`paused`）的 `StudySession` 标为 `abandoned`（`completion_reason="day_rollover"`）、关闭未结束区间与关联的 `TutoringSession`/`TutoringProblem`，并解除 `session.task_id` 绑定，使跨天未完成任务统一恢复为「未排期、未进行」且可正常从任务池左滑删除。
  2. `TutoringWorkflow._find_session` 在按 `ward_id` 查找默认会话前先执行跨天释放；且在新发起的答疑 Run（`not resume_from_checkpoint and not context_refs and not study_session_id`）上自动放弃旧线程遗留的 `open`/`submitted` `TutoringProblem`。
  3. `run_transcript.select_recent_utterances` 在构造传给模型的 `recent_utterances` 窗口时，剥离系统自动追加的 `\n先回到正在进行的任务，这个问题可以稍后再问。` 尾巴，防止该系统提示在后续多轮对话中污染模型上下文并诱导模型输出 `act=redirect`。

