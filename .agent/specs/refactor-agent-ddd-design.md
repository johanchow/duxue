---
slug: refactor-agent-ddd-design
created: 2026-09-11T23:19:07Z
status: draft
---

# refactor-agent-ddd-design spec

## 做什么 / 为什么
将 `docs/technical/design-agent.md` 重构为以 DDD 模板组织的 Companion
Orchestration Context 详情页。现有文档虽已说明边界，却混合了全局 Context
Inventory、目标业务 Context 的 Aggregate、AI Runtime 和 Coordinator 机制，难以读出
Companion 自身的领域状态、Process Manager 用例、Run 生命周期与执行协议。

## 验收标准
- [x] 文档开头明确：`Companion Orchestration` 是拥有 Thread/Run 连续性状态的
  Supporting Bounded Context；`CompanionCoordinator` 是其 Application-layer Process
  Manager；Planning、Study、Evaluation、Memory 的所有权以 `ddd-overview.md` 为准。
- [x] 以 DDD 结构依次呈现 Companion Context 的边界/统一语言、
  `ConversationThread` Aggregate Card 与 Entity Inventory、Run 生命周期状态图、
  Process Manager 用例与状态变更矩阵、Query/API 契约、基础设施映射和验收场景。
- [x] 明确一次 Turn、Thread、Run、Workflow、Checkpoint、Trace 的关系；定义
  Handle/Resume/Handoff/RecordOutcome 的触发、授权、事务、一致性、幂等和失败语义。
- [x] 单列 Run 执行协议：Coordinator 控制入口级路由，目标 Workflow 控制 Run 内步骤；
  明确 ContextEnvelope 的最小上下文、模型/工具候选校验、领域命令、Outcome、
  checkpoint/resume、SSE 的目标契约与边界。
- [x] 将 Planning、Tutoring、Reflection 收敛为目标 Context 调用契约，不在本文件复制
  它们的 Aggregate/UML；保留当前实现与目标能力的明确区分。
- [x] 不变更服务端代码、数据库迁移、API 实际行为或 `ddd-overview.md` 的所有权目录；
  Markdown 链接、Mermaid 围栏和 `git diff --check` 通过，并写入决策笔记。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `docs/technical/design-agent.md`：重排章节与图表，删除重复的全局 Inventory 和
    目标 Context 内部 Aggregate 细节；补齐 Companion Aggregate、生命周期、Process
    Manager 用例卡、执行协议、接口与基础设施契约。
  - `.agent/notes/042-agent-ddd-design-refactor.md`：记录“Companion Context 详情只拥有
    Thread/Run 连续性；目标 Workflow 的业务模型归所属 Context”的文档职责决策。
  - `.agent/specs/refactor-agent-ddd-design.md`：维护本次验收、计划和完成度。
- 测试计划：
  - 静态检查所有 Markdown 链接与 Mermaid 代码围栏完整；检查关键术语与
    `ddd-overview.md` 一致，不重新定义 Context 所有权。
  - 用 `rg` 核对文档覆盖 DDD skill 要求的 Context 边界、Aggregate/Entity、状态变更矩阵、
    Use Case、Query/API、基础设施和验收场景。
  - 运行 `git diff --check` 并人工审阅 diff；本次无代码行为变更，不运行服务端测试。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 重构为以 Companion Context 为中心的 DDD 文档结构，并收敛跨 Context 内容为契约。
- [x] 补齐 Thread/Run 生命周期、Coordinator Use Case 卡和 Run 执行/恢复协议。
- [x] 补齐 Query、Interface、Infrastructure、治理和验收规范；保留当前/目标实现边界。
- [x] 完成静态检查、diff 审阅和决策笔记。

## 备注
