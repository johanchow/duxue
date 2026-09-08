# DDD Infrastructure 层标准

- DDD Skill v2.1 将原先合并的 Interface / Infrastructure 分开：Interface 处理 transport 与认证适配；Infrastructure 实现 Repository、ORM、Outbox、Worker、外部 Gateway 与可观测性。
- 含持久化、异步处理或外部依赖的 Context 现在必须交付 Infrastructure Design Card：Ports/Adapters、Persistence/Transaction、Async Delivery/Projection、Security/Data Governance/Observability 四部分。
- Application / Domain 仅依赖 Port；具体 SQLAlchemy、HTTP/SDK、Queue、模型/工具 Adapter 在 composition root 装配。现有直接依赖可作为过渡实现记录，但不能伪装成领域行为。
- 模板要求设计迁移/兼容/回滚、幂等、重试/死信/对账/重放和外部依赖故障降级；不适用时必须说明原因。
