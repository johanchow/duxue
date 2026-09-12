---
slug: refine-memory-ddd-design
created: 2026-09-11T15:25:49Z
status: done
---

# refine-memory-ddd-design spec

## 做什么 / 为什么
将 `design-memory.md` 对齐 `ddd-overview.md` 与 DDD skill：明确所有上游/下游
Context、收口事实入账边界、区分 Aggregate / Evidence Ledger / Query DTO，并补齐
参与者类型、接口契约和 Infrastructure Design Card，使 Memory & Understanding Context
成为可执行的独立设计契约。

## 验收标准
- [x] Context 边界、邻接图、触发矩阵与异步契约均纳入 Behavior Analysis 上游，并把
  Planning、Evaluation & Reflection、Companion 作为受权 `MemoryBundle` 查询下游；内容与
  `ddd-overview.md` 一致。
- [x] 所有跨 Context 事实流统一为“发布方 Use Case → 发布方 Outbox → Memory Consumer
  Adapter → `IngestLearningFact` → Evidence Ledger”；删除任何上游直接写
  `learning_events` 的表述或图线。
- [x] 明确 Evidence Ledger 的 DDD 分类和写边界：`LearningEvidence` 作为轻量 Aggregate
  Root（不可变、来源四元组幂等），并与 `EpisodicMemory`、`DerivedSignal` 的聚合关系、
  Repository Port、物理 Schema 迁移前置条件一致。
- [x] 三张关键时序图均附 Participant Inventory，且 Worker/Scheduler 被标为
  Infrastructure、只触发 Use Case；`MemoryBundle` 被改为 Query response DTO，
  `MemoryFacade` 被改为唯一跨 Context 授权 Query 边界。
- [x] 补齐 Context 的接口/事件契约与 Infrastructure Design Card：Port/Adapter、持久化
  与事务、异步投递/Projection、安全/留存/可观测性；明确现有 Schema 的缺口由
  `tutoring-reflection-memory-workflows` spec 实施，不改代码或迁移。
- [x] 文档链接、Mermaid 围栏、术语/契约一致性和 `git diff --check` 通过；不修改 Server
  代码、数据库迁移或既有未提交代码文件。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `docs/technical/design-memory.md`：更新边界、Aggregate Map、事实流、用例矩阵、
    时序图 inventory、CQRS、契约和基础设施章节。事实账本采用 `LearningEvidence`
    Aggregate Root 的目标模型；只描述所需的目标 Schema 约束，不改物理 Schema。
  - `docs/technical/ddd-overview.md`：仅在需要时补充 `LearningEvidence` 术语/写入权，
    不复制 Memory Context 内部 Aggregate 设计。
  - `.agent/notes/040-memory-ddd-contract-refinement.md`：记录 Evidence Ledger 的
    Aggregate 决策、下游授权查询边界及与后续 Schema workflow 的关系。
- 测试计划：
  - 使用 `rg` 检查 Overview 与 Memory 在 Context 名称、上游/下游、
    `LearningFactRecorded.v1` 和 `MemoryBundle` 契约上的一致性；确认不存在上游直接写
    Ledger 的流程描述。
  - 检查每个 Mermaid 代码围栏配对、三张时序图紧随 Participant Inventory，以及
    Infrastructure Design Card 的四个必需小节。
  - 运行 `git diff --check`；此为纯文档变更，不运行服务端测试。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 对齐 Context 边界、术语、上下游与跨 Context 事实流。
- [x] 定义 LearningEvidence Aggregate、更新 Aggregate Map、用例矩阵和目标 Schema 前置条件。
- [x] 补齐时序图 Participant Inventory、Query/事件契约和 Infrastructure Design Card。
- [x] 校验文档与 Overview 的一致性、Mermaid/链接及 diff；写入决策笔记并审阅变更。

## 备注
- 本次不实现 `learning_events`、Episode、Signal 的迁移或约束；这些物理变更仍由
  `tutoring-reflection-memory-workflows` spec 负责。若其实际实现选择不同的 Aggregate
  或幂等键，必须先更新本设计再编码。
