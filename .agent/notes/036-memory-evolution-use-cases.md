# Memory 演进核心用例

- `design-memory.md` 将 Memory 演进从零散的 Aggregate / Worker 描述提升为核心用例闭环：`CloseTutoringSession` → `IngestLearningFact` → `SettleEpisodicMemory` → `ProposeCandidateSignal` → `EvolveSignals` → `RebuildLongTermProfile`。
- 原始 Ward 消息、模型候选、Trace 和“没有活动”均不能直接成为 Memory；只有通过目标 Context 校验、随业务事务写出的稳定 Fact 才可入 Evidence Ledger。
- `tutoring.session_closed` Fact 是 Episode 结算的显式触发器。暂停、断连和无活动保持可恢复状态，不能被 Worker 猜测为关闭。
- Policy 的独立证据单位是 Episode / `aggregate_ref`，不是会话内消息数量；`long_term` 为独立 scope 的 Candidate，不能把 `recent` Signal 原地改名升级。仅 `active + long_term` 可投影长期画像。
- 3.2.0 使用单张 UML 时序图表达端到端机制：Interface、Coordinator、Workflow、Validator、Application Service、Aggregate、Outbox、Consumer、Ledger、Worker、Policy、Projection 均按同步或异步交互顺序展示；拒绝、未形成 Fact、会话未关闭及 Policy 未达门槛均有明确分支。
