---
slug: align-agent-run-failure-semantics
created: 2026-09-12T02:29:48Z
status: done
---

# align-agent-run-failure-semantics spec

## 做什么 / 为什么
将 `design-agent.md` 中 Run 的异常、超时、取消与恢复语义嵌入现有关键设计位置，消除“异常转失败状态”的文字说明与现有状态机、触发矩阵、Use Case 和 `WorkflowOutcome` 契约之间的不一致。范围仅限文档设计，不变更运行时代码或数据库 schema。

## 验收标准
- [x] 第 2.3 的 Run 状态图和状态说明定义 `failed`、`timed_out`、`cancelled` 的进入、恢复或终结语义，并维持既有 focus/attempt fence 规则。
- [x] 第 3.1 触发矩阵与第 3.2 Use-case Cards 覆盖模型/工具失败、预算耗尽、用户取消与流式连接断开，明确触发者、状态、幂等和用户可见结果。
- [x] 第 5 章的 `WorkflowOutcome` 以结构化字段表达失败分类、是否可重试和允许的下一步；SSE 段落说明断流、重连与 Run 生命周期的关系。
- [x] 原有正常完成、Handoff、重复请求和迟到 Outcome 语义不被削弱；验收场景覆盖至少一个失败、超时、取消或恢复路径。
- [x] 文档链接、状态枚举和叙述互相一致，`git diff --check` 通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `docs/technical/design-agent.md`：只编辑 2.3、3.1、3.2、5 章及第 8 章相关验收场景；不新设泛化 Runtime 章节，不改动目标 Workflow 的业务规则。
  - `.agent/notes/044-agent-run-failure-semantics.md`：记录失败分类应嵌入控制流/契约而非独立章节的决策。
- 测试计划：
  - 用 `rg` 交叉检查 Run 状态图、触发矩阵、`WorkflowOutcome.run_status` 与 Gherkin 场景的状态名称和失败字段一致。
  - 运行 `git diff --check`，人工审阅 diff，确认没有将 Gateway 的技术重试与业务状态转换混为一层。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 对齐状态图、触发矩阵和 Use-case Cards。
- [x] 对齐 Outcome/SSE 契约和验收场景。
- [x] 写入设计决策笔记并完成一致性/diff 验证。

## 备注
