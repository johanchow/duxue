# Companion Agent DDD 文档重构

- `design-agent.md` 只完整建模 `Companion Orchestration`：`ConversationThread`、`AgentRunLink`、Run 生命周期，以及 `CompanionCoordinator` Process Manager 的用例与执行协议。
- Planning、Study 与 Evaluation 的业务 Aggregate、领域规则和详细 Workflow 状态不再在 Agent 文档复制；本文仅维护 Coordinator 对它们的 `RunInvocation` / `WorkflowOutcome` 调用契约。
- Agent Runtime 的模型、工具、SSE 和 Checkpoint 是 Application / Infrastructure 能力。模型只能提出候选；Target Context 的类型化 Use Case 和 Aggregate 才能改变业务状态或发布 Learning Fact。
- 为保证异步/流式安全，Run 的结算与展示应由 `run_id + turn_id + attempt` 和 Thread focus 共同 fence；旧 Run 的迟到 Outcome 不可覆盖新 Handoff。
