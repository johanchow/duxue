# Memory DDD 文档结构

- `design-memory.md` 改为 Memory & Understanding Bounded Context：上游通过 `LearningFactRecorded.v1` 发布事实，Memory 仅持久化证据副本和派生理解；下游 Companion 通过 `MemoryFacade` 查询。
- 写 Aggregate 只有 `EpisodicMemory` 与 `DerivedSignal`；`LearningEvent` 是不可变证据实体，`LongTermProfile` 是 CQRS 投影，Working Memory 属于 Companion Runtime。
- 文档补充 Context Map、Aggregate Map、DerivedSignal 生命周期图和既有 Command–Event–Projection 图链接；物理 Schema 仍以 `design-server.md` 为唯一事实源。
