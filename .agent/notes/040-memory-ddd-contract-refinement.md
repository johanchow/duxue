# Memory DDD 契约收敛

- Memory Evidence Ledger 采用 `LearningEvidence` 轻量 Aggregate Root：`learning_events` 是其
  append-only 物理记录，`IngestLearningFact` 和本地 `RecordSignalChallengeEvidence` 是唯一写入口。
- 上游 Context 只通过自身 Outbox 发布 `LearningFactRecorded.v1`；Memory Consumer Adapter
  负责传输，Memory Use Case 负责 ACL、幂等和本地 Aggregate 写入。
- `MemoryBundle` 是唯一跨 Context 的受权 Query response DTO，不是 Projection，也不携带
  Working Memory；Planning、Evaluation & Reflection、Companion 均经此边界查询。
- 本次只更新设计。来源四元组、Episode/Signal identity、证据链接唯一约束的实际迁移继续由
  `tutoring-reflection-memory-workflows` spec 负责；实现不得偏离本设计。
