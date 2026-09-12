---
slug: remove-server-memory-domain-mapping
created: 2026-09-12T03:40:49Z
status: draft
---

# remove-server-memory-domain-mapping spec

## 做什么 / 为什么
删除 `design-server.md` 中重复的 Memory Context 专属物理映射章节，使 `domain-memory.md` 唯一拥有 Memory 的 Infrastructure Mapping；Server 文档仅保留全局物理 Schema、索引、队列和运维事实。

## 验收标准
- [x] `design-server.md` 不再有按 Memory 领域概念说明的专属章节或表；其表、索引、队列、留存等全局物理内容保持不变。
- [x] 后续 API、权限、队列、运维章节编号连续；没有断链或指向被删除章节的引用。
- [x] `domain-memory.md` 仍链接 `design-server.md` 为物理 Schema/索引/队列的唯一事实源，`git diff --check` 通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `docs/technical/design-server.md`：删除第六章 Memory 专属映射；将之后的章节顺延为六至九章。
  - `.agent/notes/047-server-memory-mapping-removal.md`：记录 Domain Infrastructure Mapping 与全局 Server 物理事实的分界。
- 测试计划：
  - 使用 `rg` 检查不存在删除章节标题、`mem:work` 或按领域概念的重复映射表，检查章节编号连续。
  - 检查 `domain-memory.md` 到 `design-server.md` 的引用仍存在，并运行 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 删除重复 Memory 映射并顺延章节编号。
- [x] 写入决策笔记，完成结构、引用和 diff 验证。

## 备注
