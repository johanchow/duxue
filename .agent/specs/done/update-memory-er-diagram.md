---
slug: update-memory-er-diagram
created: 2026-08-30T06:20:02Z
status: done
---

# update-memory-er-diagram spec

## 做什么 / 为什么
更新 `design-server.md` 的 ER 图，使其与已补充的记忆设计一致：以不可变学习事件作为事实根，近期记忆和理解信号分别建立可追溯的事件关联；长期画像只保存已激活理解的聚合快照。

## 验收标准
- [x] ER 图包含 `learning_events`、`episodic_memory_events`、`derived_signals` 与 `derived_signal_events`，且两张关系表的外键方向清晰。
- [x] `episodic_memories` 明确是近期摘要，能通过关联表追溯多个事实事件。
- [x] `derived_signals` 明确保存候选/激活/质疑/过期的可校正理解，并通过关联表保留支持、反证与 Ward 确认事件。
- [x] `long_term_profiles` 保持每 Ward 一行的聚合读模型；其字段覆盖专注基线、知识卡点、兴趣、有效策略、计划偏好、自我调节、节律和明确沟通偏好，并注明它不直接充当事件证据源。
- [x] ER 图中新增表均在索引与约束章节拥有相应的唯一约束或查询索引说明。
- [x] Mermaid ER 代码块通过语法与字段引用的人工核对，且 `git diff --check` 无空白错误。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `docs/technical/design-server.md`：更新 §3.1 ER 关系、记忆相关实体字段与 §3.2 索引/约束说明。
  - `docs/technical/design-memory.md`：作为信号类型、状态、`value` Schema 与晋升边界的唯一语义规范。
  - `.agent/notes/`：补充一则设计决策笔记，记录“事实事件为证据根、长期画像为物化快照”的边界。
- 测试计划：
  - 审核 Mermaid 关系中的所有端点均存在，关系表均有两个明确 FK。
  - 运行 `git diff --check`。
  - 用 `rg` 核对新增表、关系和索引均在设计文档中出现。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 建立 spec 并完成验收标准与实施计划。
- [x] 更新 ER 图、实体字段与索引说明。
- [x] 补充 Signal Taxonomy、枚举及各类型的 `value` Schema。
- [x] 写入设计决策笔记并执行文档一致性检查。
- [x] 审阅 diff，用户已验收，归档 spec。

## 备注
