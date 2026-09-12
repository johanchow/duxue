---
slug: add-system-ddd-overview
created: 2026-09-11T14:35:14Z
status: draft
---

# add-system-ddd-overview spec

## 做什么 / 为什么
建立全系统 DDD Overview 作为 Domain Inventory、Context Map、跨 Context
所有权与协作规则的唯一来源；将 Server 与 Memory 设计文档明确为其引用方，消除
“Domain / Bounded Context / 表与聚合”混写造成的重复和边界歧义。

## 验收标准
- [ ] 新增 `docs/technical/ddd-overview.md`，含完整 Domain Inventory：每个子域的
  Core / Supporting / Generic 分类、Bounded Context、责任与非目标、可变概念所有权、
  上下游和集成方式。
- [ ] Overview 含独立的 Context Map（不出现表、ORM、队列或 Controller）和独立的
  Layered Architecture Map；前者表达业务所有权/契约，后者表达 Interface →
  Application → Domain Context → Infrastructure 依赖方向。
- [ ] Overview 含跨 Context 术语与写入所有权表、稳定 Integration Event 契约目录、
  跨 Context 协作与一致性规则，并明确 Context 文档、物理 Schema 与运行时设计的
  单一事实源边界。
- [ ] `design-server.md` 的现有“领域模型与限界上下文”章节改为系统级 Overview 的链接
  与简要定位；保留分层、物理 Schema、运行时/队列和运维为该文档的唯一职责，不复制
  Context 内部模型。
- [ ] `design-memory.md` 链接 Overview，并统一使用 `Memory & Understanding Context`；
  删除其“未来维护全系统 Context Map”的悬置表述，但不在本次改动 Schema、聚合字段或
  Workflow 设计。
- [ ] Markdown 链接、Mermaid 语法与 `git diff --check` 通过；不修改服务端代码、迁移或
  任何既有未提交代码文件。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `docs/technical/ddd-overview.md`（新增）：写入系统级 DDD Inventory、两张职责分离
    的 Mermaid 图、术语/所有权、事件契约目录和协作规则；各 Context 详情只链接，不复刻。
  - `docs/technical/design-server.md`：以新 Overview 替换现有混合实体与 Context 的总图
    为引用性概览，并在层次架构说明中标注 Context 模块和 Worker 的正确归属。
  - `docs/technical/design-memory.md`：更新文档关联和边界措辞，使其作为 Context 详情页
    消费系统级 Context Map；本轮不调整现有聚合或物理 Schema。
  - `.agent/notes/039-system-ddd-overview.md`（新增）：沉淀全局/局部文档职责划分和
    Context Map 不承载技术实现细节的决定。
- 测试计划：
  - 使用 `rg` 检查三个文档的交叉链接、Context 名称和关键契约名称一致；确认 Context Map
    不包含数据库、ORM、队列、Controller、Aggregate 或表字段。
  - 使用 Mermaid 代码块静态检查（围栏完整、节点 ID 合法），并运行 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 建立系统级 Overview 的 Inventory、Context Map、Layered Architecture Map 与协作规则。
- [x] 将 Server 文档改为系统/物理设计定位并链接 Overview。
- [x] 将 Memory 文档改为引用 Overview，并统一 Context 命名与边界措辞。
- [x] 校验 Markdown/Mermaid、交叉链接与 diff；写入决策笔记并审阅变更。

## 备注
- 本 spec 不修复 Memory 与物理 Schema 的字段/约束不一致，也不改代码；该问题应在现有
  `tutoring-reflection-memory-workflows` 或独立 schema 对齐变更中处理。
