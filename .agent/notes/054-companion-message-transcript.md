# CompanionMessage：学生可见对话记录的边界

> 日期：2026-09-14  
> 关联规范：`.agent/specs/companion-message-transcript.md`

## 决策

- 在 `Companion Orchestration` Context 中采用 `CompanionMessage` 作为 Ward-facing、append-only 的 transcript record/read model；不采用 `CompanionInteractionEntry`，因为需求的核心是聊天消息，`Entry` 语义过宽。
- `CompanionMessage` 是 Application 维护的 append-only transcript journal record，不是 Domain Entity、Aggregate、Domain Event 或可重建 projection。它没有独立业务生命周期和行为，不能承担 `save()`、查询或模型调用。
- `ConversationThread` 仍是唯一写 Aggregate，且不内嵌无限消息集合；`AgentRunLink` 仍是其唯一 Child Entity。Message 通过 `thread_id/run_id/turn_id` 引用关联，按序列分页查询。
- `CompanionCoordinator` 作为 Application Process Manager 可以调用 Aggregate Repository 与 `CompanionTranscriptStore` **Port** 编排同一 Unit of Work，但不得直接操作 ORM/SQL。领域行为与 Workflow Validator 决定 Turn/Outcome 是否可见；Infrastructure Adapter 才执行实际持久化。
- 已接受的 Ward Turn 与 Thread/Run/命令幂等记录在同一短事务中追加 Ward journal record；通过 `run_id + turn_id + attempt + focus` fence 且经过展示/安全校验的最终 Outcome，在其短事务中追加 companion journal record。SSE delta 仅临时显示，最终消息才持久化。
- `author_type` 仅可为 `ward | companion`。System prompt、模型推理、内部路由、Trace、Checkpoint、未校验候选和原始工具输出不属于 transcript，也不能用于跨 Context Handoff 或 Memory。

## 后续影响

- 真实实现前，应先由 `design-server.md` 定义物理表、索引、唯一约束、留存和媒体删除规则；本领域文档只维护语义和契约。
- 当前 `tutoring_messages` 是 Study/Tutoring 既有模型。本决策不迁移或复制它；如未来上线统一 transcript，须另立迁移设计，避免两处保存全文。
