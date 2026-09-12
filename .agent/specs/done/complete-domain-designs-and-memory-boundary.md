---
slug: complete-domain-designs-and-memory-boundary
created: 2026-09-12T03:26:05Z
status: done
---

# complete-domain-designs-and-memory-boundary spec

## 做什么 / 为什么
将 `domain-planning.md`、`domain-study.md`、`domain-evaluation.md` 从 Workflow 摘要补齐为符合 `domain-driven-design` skill 的 Context 技术设计；同时收敛 `design-server.md` 的 Memory 内容，只保留物理实现映射，消除其对业务记忆模型、Working Memory 和衰减算法的重复且过期描述。

## 验收标准
- [x] 三个业务 Domain 文档各自包含边界/上下游、Aggregate Map 与 Inventory、状态变更触发矩阵和 Use Case Cards、Query/Interface、Infrastructure Mapping、跨 Context 事件与验收场景；概念类型遵守 DDD 层边界。
- [x] `TutorWorkingState`、`PlanningWorkingState`、`ReflectionWorkingState` 被明确为目标 Workflow Runtime state，不冒充业务 Aggregate；Evaluation 的 `ReflectionReportVersion`、`FocusKit` 分类为明确的 Aggregate 或 Projection，不再混合标注。
- [x] 每个跨 Context `LearningFactRecorded.v1` 关系明确发布 Context、接收 Context、消费 Use Case、幂等/失败边界，且不复制 `domain-memory.md` 的 Memory 内部规则。
- [x] `design-server.md` 不再定义三层 Memory 业务模型、Working Memory TTL/Redis key 或衰减算法；替换为指向 `domain-memory.md` 的物理映射说明，并与 Companion 的 per-Run state 边界一致。
- [x] Mermaid 图、链接、旧术语与文档章节一致；`git diff --check` 和结构/引用扫描通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `docs/technical/domain-planning.md`：补本地/外部边界、Aggregate 细节、Use Case/触发矩阵、PlanDraft 查询/接口、事务/Outbox/投影与必要图。
  - `docs/technical/domain-study.md`：区分 Study/Tutoring Aggregate 与 Runtime State，补 Use Case、查询、接口、工具 adapter、会话 Fact/Outbox 与结算时序。
  - `docs/technical/domain-evaluation.md`：澄清 Report/FocusKit 的 Aggregate/Projection 分类，补证据消费、Use Case、Query、接口、投影与补充报告事件流。
  - `docs/technical/design-server.md`：将第六章替换为 Memory 的物理实现映射与唯一归属链接，不复制 domain-memory 业务语义；修正 `derived_signals` 指向。
  - `.agent/notes/046-domain-ddd-completeness-and-memory-ownership.md`：记录 DDD 文档与 Server 文档的 Memory 边界。
- 测试计划：
  - 以 `rg` 检查每个业务 Domain 的 DDD 必要章节、Use Case 名、Integration Event、Query/Interface/Infrastructure Mapping 与 Mermaid 图。
  - 扫描 `design-server.md`，确认不再出现 `mem:work`、Working Memory Redis/TTL 或衰减公式，并保留对 `domain-memory.md` 的物理映射链接。
  - 运行 `git diff --check`，人工审阅跨 Context 事件方向和概念类型，避免将 Runtime/Projection 写成 Aggregate。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 补齐 Planning DDD 设计与集成契约。
- [x] 补齐 Study/Tutoring DDD 设计与运行时边界。
- [x] 补齐 Evaluation/Reflection DDD 设计与事件/投影。
- [x] 收敛 Server 的 Memory 内容，记录决定并完成验证。

## 备注
