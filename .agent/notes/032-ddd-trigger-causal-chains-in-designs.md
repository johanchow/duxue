# DDD 因果链补全

- Memory 设计补充了触发矩阵和两张 Mermaid 时序图，区分跨 Context 的 `LearningFactRecorded.v1` 与 Memory 本地 Domain Event，并明确事实入账、情境结算、Signal 演进、Ward 纠正、Profile 重建和归档的调用链。
- Agent 设计补充了 Thread/Run、目标 Context 命令和 Memory 事件消费的触发矩阵，以及“已确认业务结果 → Outbox → Memory Consumer → Evidence Ledger”时序图。
- 关键约束：Adapter 负责收到/投递消息；Application Handler 将其转成本地命令；Aggregate 执行业务状态变更并产生本地 Domain Event；跨 Context 只发布稳定 Integration Event。Coordinator 不写 Memory，也不把 Trace 或模型候选当作业务事件。
