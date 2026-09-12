# Domain DDD 完整性与 Memory 所有权

- Planning、Study、Evaluation 文档分别拥有本 Context 的 Aggregate、Use Case、Query/View、接口和应用端口映射；Workflow 不能替代 DDD 的状态变更与事务设计。
- Working State 是 Target Workflow Runtime/Checkpoint 状态，不是业务 Aggregate 或 Memory Context 模型。它按 Run/会话版本恢复，不能使用按 Ward 共享的 Memory key。
- `domain-memory.md` 是所有 Memory 业务模型、Fact→Evidence→Episode/Signal/Profile 演化、衰减和删除语义的唯一事实源；`design-server.md` 只保留 Memory 表、索引、队列、Outbox/Worker、存储与运维的物理映射。
