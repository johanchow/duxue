---
slug: companion-message-transcript
created: 2026-09-14T00:00:00Z
status: done
---

# companion-message-transcript spec

## 做什么 / 为什么

在不让 `ConversationThread` 承担无限消息集合的前提下，为 Companion Orchestration 定义学生可见的持久化对话 journal `CompanionMessage`，明确它不是 Aggregate/领域 Entity，且由 Application 通过 `CompanionTranscriptStore` journal port 在已接受 Turn 与已验证 Outcome 的短事务中写入；为后续“我 ↔ 读学 AI”历史展示提供唯一设计依据。

## 验收标准

- [x] `docs/technical/domain-companion.md` 明确 `CompanionMessage` 是 Companion Context 归属的、不可变的 Ward-facing transcript record / read model，不是 `ConversationThread` Child Entity、Aggregate、Domain Event、Memory、Trace 或 Checkpoint。
- [x] 文档在 Query/CQRS 与物理设计中定义 `CompanionMessage` 的作者范围（`ward | companion`）、附件/目标对象引用边界，以及 `system prompt`、模型推理、内部路由与未校验输出绝不可进入消息记录的约束；领域文档不放代码 DTO 或表字段定义。
- [x] 文档定义 Application / Domain / Port / Infrastructure 的职责边界：领域行为决定 Turn/Outcome 是否接受；Application 编排同一 Unit of Work；Aggregate Repository 与 journal store 分别负责读写抽象；SQLAlchemy/PostgreSQL Adapter 执行实际持久化；任何 Entity 不直接数据库读写。
- [x] 文档定义追加与读取链路、`command_id` 和 `run_id + turn_id + attempt + sequence` 的幂等/fence 关系、最终 SSE 输出的持久化时机，以及按 Thread 游标分页读取的 Query 契约。
- [x] 文档将物理表、索引、迁移、留存策略明确留给 `docs/technical/design-server.md`，不在本领域文档复制物理设计；仅在需要处建立链接。
- [x] 本次只改设计文档与 spec，不改 Flutter、服务端实现、ORM、迁移或接口行为。

## 实现计划（Gate 1：填完等人确认，不许自转）

- 影响文件：
  - `docs/technical/domain-companion.md`：补充 `CompanionMessage` journal 的边界、读写链路和 Query 契约；修订现有“Thread 不是完整聊天副本”“完整聊天不得跨 Context Handoff”的表述，不在此文放代码 DTO 或物理字段。
  - `docs/technical/design-server.md`：维护 journal store 的表、约束、索引、合并/去重与删除策略。
  - `.agent/specs/companion-message-transcript.md`：保留本次验收、范围和完成度清单。
  - `.agent/notes/054-companion-message-transcript.md`：记录为何选择独立 append-only read model，而非向 Thread 增加 Child Entity 或使 Entity 承担持久化职责。
- 实施步骤：
  1. 在 Companion 边界和术语中定义 `CompanionMessage` 的所有权、非目标和安全可见性边界。
  2. 在 Aggregate Map 与对象清单中显式排除它作为 Aggregate/Child Entity，并引入 `CompanionTranscriptStore` 与分页 Query 契约。
  3. 在 `HandleCompanionTurn`、`RecordWorkflowOutcome` 和 SSE 章节补充两个短事务的追加时机、幂等键/fence、最终输出落库与读取 API。
  4. 在基础设施治理章节明确 port/adapter 分层、物理事实归属和删除/留存边界。
  5. 审阅文档交叉引用、`git diff --check` 与完整 diff；记录决策笔记。
- 测试计划：
  - 文档变更不引入可执行行为；执行 `git diff --check`，并人工核对术语、所有权及与 `domain-planning.md` / `design-server.md` 的链接不重复物理事实。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）

- [x] 建立 spec 并界定本次仅文档范围
- [x] 更新 Companion 领域边界与对象分类
- [x] 更新用例链路、Repository Port 与 Query 契约
- [x] 更新治理、删除与物理设计引用
- [x] 复核 diff 与文档一致性
- [x] 写入决策笔记

## 备注

- 现有 `tutoring_messages` 属于 Study/Tutoring 的既有物理模型；本次不迁移、不复制其内容，也不改其实现。
- `CompanionMessage` 是统一 Ward UI 的可见 transcript；它可按 `run_id` 分段展示，但完整历史不得作为跨 Context Handoff 载荷或无边界模型上下文。
