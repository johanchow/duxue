# Companion Application 层设计

- `CompanionCoordinator`、`IntentRouter`、Workflow 与 Gateway 是 Application / Infrastructure 组件，不是领域 Entity；Entity Inventory 只描述 `ConversationThread`、`AgentRunLink` 等领域状态。
- Coordinator 编排一次 Turn 应进入哪个业务 Run；目标 Workflow 才编排该 Run 内是否调用模型、工具、等待 Ward 或发出领域命令。`ModelGateway` 才实际发起模型调用。
- 模型候选必须经过 `OutputValidator`；目标 Context 的领域服务/聚合才可以在本地事务写业务状态、稳定 Fact 与 Outbox。Coordinator 不跨 Context 写入。
- 新增 Mermaid 的组件分层图、Turn 时序图和模型/工具受控循环图；现有 Archify 图保持不变，按用户本次要求未使用 Archify 生成新图。
