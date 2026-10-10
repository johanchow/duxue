# 拆分 Study 与 Tutoring 为两个 Domain

日期：2026-10-10

- 决策：`domain-study.md` 拆为 Study（`StudySession`、`StartCue`）和 Tutoring（`TutoringSession`、`ProblemRecord`、`TutorPermitPolicy`、`TutoringTurnLoop`、发音 act）。`ddd-overview.md` 的 Domain 从 8 个变为 9 个。
- 原因：两者业务问题、变化速度和上游依赖不同；答疑的 Agent 控制流已占原文约一半。
- 边界：`StartCue` 留在 Study，因为 `AcceptStartCue` 要与 `StudySession` 同事务 `start()` / `pause()`（见 note 105）。Tutoring 经受权 Query `GetStudySession` 读取会话状态与 `task_id`，不订阅事件、不调用其聚合。`tutoring.*` 的 `LearningFactRecorded.v1` 由 Tutoring 发布，`StudySessionCompleted.v1` 仍由 Study 发布。
- 取舍：学习会话结束后答疑不自动关闭，只是不再追加新轮次，关闭仍只由 `CloseTutoringSession` 完成；`open()` 的前置检查变为最终一致。
- 只改文档，未改代码和表。
- 遗留：`docs/technical/diagrams/` 下由工具生成的 context-map（`design-memory-context-map`、`design-agent-context-map`）仍显示合并的 Study 节点，下次重新生成时同步；历史笔记中的 `domain-study.md` 引用保持原样。
