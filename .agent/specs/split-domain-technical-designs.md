---
slug: split-domain-technical-designs
created: 2026-09-12T03:02:09Z
status: draft
---

# split-domain-technical-designs spec

## 做什么 / 为什么
将技术设计从“按技术主题”调整为“按 Bounded Context”：把现有 Companion 与 Memory 文档重命名为 `domain-companion.md`、`domain-memory.md`，并新增 Planning、Study、Evaluation 三个 Domain 文档。每个业务 Domain 文档拥有自身 Aggregate、业务不变量、Workflow Definition、Working State、业务工具、事实写回与目标 UI 契约；全局/物理文档只链接，不复制详细设计。

## 验收标准
- [x] `design-agent.md` 和 `design-memory.md` 分别无损迁移为 `domain-companion.md` 与 `domain-memory.md`；仓库中不再有指向旧文件名的链接或文本引用。
- [x] 新增 `domain-planning.md`、`domain-study.md`、`domain-evaluation.md`；每份都明确 Context 边界、领域模型与不变量、Use Case、具体 Workflow Definition、Working State/ContextSpec、工具/模型候选边界、Fact/Outbox、目标 UI 契约、失败与验收场景。
- [x] `domain-companion.md` 仅拥有入口、Thread/Run、Coordinator、Handoff 与通用运行协议；目标 Context 的详细业务/Workflow 设计均改为链接对应 Domain 文档。
- [x] `design-server.md` 增加 Context Design 索引，并仅保留物理 schema、运行时、API/Worker/运维映射；`ddd-overview.md`、`AGENTS.md` 和所有内部链接使用新命名并保持单一事实源。
- [x] 文档中的链接存在且相互一致；`git diff --check` 通过；对新增文档执行关键章节、Mermaid fence 和旧文件名扫描。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `docs/technical/design-agent.md` → `docs/technical/domain-companion.md`：保持 Companion Orchestration 的既有内容，替换其与目标 Domain 的边界表和链接，删除对目标 Workflow 细节的承载暗示。
  - `docs/technical/design-memory.md` → `docs/technical/domain-memory.md`：无损重命名并修复所有入站/出站链接。
  - `docs/technical/domain-planning.md`：新增 Planning & Scheduling Context 和固定计划协商 Workflow 的具体设计。
  - `docs/technical/domain-study.md`：新增 Study & Tutoring Context 和受限 ReAct Workflow 的具体设计。
  - `docs/technical/domain-evaluation.md`：新增 Evaluation & Reflection Context 和证据版本化复盘 Workflow 的具体设计。
  - `docs/technical/design-server.md`、`docs/technical/ddd-overview.md`、`AGENTS.md`：改为 Context 设计目录/链接与物理实现映射，移除旧命名链接。
  - `.agent/notes/045-domain-document-ownership.md`：沉淀文档所有权与链接方向。
- 测试计划：
  - 使用 `rg` 验证旧文件名在仓库中归零；验证新文件、文档内相对链接和 Context 索引均存在。
  - 使用脚本或文本检查验证每个新业务 Domain 文档具备边界、模型、Workflow、State/Context、Tool/Model、Fact/Outbox、UI、Failure、验收等章节。
  - 执行 `git diff --check` 并审阅 diff，确认没有重复复制 Memory、Companion 或物理 schema 的唯一事实源。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 重命名 Companion / Memory 文档，更新全仓链接和目录。
- [x] 编写 Planning、Study、Evaluation 的 Context 与 Workflow 设计。
- [x] 更新 Server / DDD / 项目导航的引用和单一事实源边界。
- [x] 写入决策笔记，执行链接、结构、旧命名与 diff 验证。

## 备注
