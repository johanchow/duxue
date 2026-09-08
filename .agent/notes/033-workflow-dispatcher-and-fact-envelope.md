# Workflow dispatcher 与事实信封

- `CompanionCoordinator` 只构造 `RunInvocation` 并更新 Thread/Run；`SqlAlchemyWorkflowDispatcher` 负责按 `agent_type` 调用唯一已注册 workflow。未实现的 Tutoring / Reflection 仍只返回 Run 生命周期元数据，不能伪造业务回复。
- `PlanningWorkflowAdapter` 负责建立 Planning 的最小 `ContextEnvelope`、LangGraph checkpoint 和结构化 `WorkflowOutcome`；Coordinator 不再直接构建 Memory 上下文或依赖 Planning 的输入细节。
- Outbox 统一发布自包含的 `LearningFactRecorded.v1` 信封。`SqlAlchemyMemoryCommandService` 以来源四元组复用 Evidence Ledger 的唯一约束实现重复投递无副作用，且消费端写入不会再次发布同一 Outbox 事件。
- `PlanDraft.confirm()` 的应用服务语义保持幂等：已确认草稿再次确认时返回同一日程，不再次写事实或 Outbox。
- 旧 Plan Intake 的“今天”判断改用 `now().date()`（UTC），与 API/数据日期语义一致，避免主机本地日期跨零点造成 UTC 请求被拒绝。
