# DDD 状态变更触发标准

- DDD skill v2.2 明确每个重要写路径都必须交付 `Trigger → Application → Domain → Event/Projection` 矩阵；领域方法和领域事件不能脱离调用者单独列出。
- Integration Event 的接收分两层：Infrastructure consumer adapter 负责传输收取、投递与重试；接收 Context 的 Application Event Handler 负责版本校验、幂等、ACL 转译、事务并发起本地命令。不得跨 Context 直接调用或修改生产方 Aggregate。
- 同 Context 的强一致不变量由 Application Service 在一个本地事务中同步调用 Aggregate / Domain Service；延后反应、跨 Context 协作才使用 Outbox、事件消费者与最终一致性。每个异步反应必须记录新的事务、幂等、顺序和失败/对账策略。
- 模板增加状态变更矩阵、入站事件 Command Card 字段，并要求异步或跨 Context 写路径配套时序图。
