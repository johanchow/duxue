# Companion Agent DDD 文档结构

- `design-agent.md` 以 `Companion Orchestration` 作为 Supporting Context：Coordinator 是应用层 Process Manager，不是第四个 Agent、业务 Aggregate 或跨 Context 写入口。
- `ConversationThread` 是入口连续性 Aggregate；`AgentRunLink` 只持有受权的 `run_ref` / `context_refs`。`AgentCheckpoint` 与 `AgentTrace` 分别是恢复和审计基础设施，不能复制 Prompt、完整聊天或业务领域状态。
- 计划、答疑、复盘各自拥有领域 Aggregate 与不变量；Coordinator 只路由一次 Run。Memory 使用 `MemoryFacade` 受权读，业务 Context 用版本化 Learning Fact 经 Outbox 与其最终一致集成。
- 文档标记了当前已实现的 Coordinator/Planning Adapter 基础，以及 Tutoring、Reflection、SSE 等仍属目标契约，避免设计状态与代码状态混淆。
