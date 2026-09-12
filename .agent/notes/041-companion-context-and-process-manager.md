# Companion Context 与 Process Manager 的层次

- `Companion Orchestration` 是拥有 `ConversationThread`、`AgentRunLink` 与运行连续性状态的 Supporting Bounded Context，不是无状态的应用工具，也不是核心学习业务领域。
- `CompanionCoordinator` 是该 Context 的 Application-layer Process Manager：只负责受权 Run 的路由、连续性与 Handoff，不拥有 Planning、Study、Evaluation 或 Memory 的 Aggregate、领域规则或跨 Context 写权限。
- 系统级 DDD Overview 必须同时说明这两个层次，避免将 Context 与其实现组件互相等同，或把 Coordinator 误称为独立 Agent。
