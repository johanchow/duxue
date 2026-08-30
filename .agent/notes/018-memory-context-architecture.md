# 孩子理解、记忆与 AI 上下文架构

- 新增 `docs/technical/design-memory.md`，将长期学生陪伴 AI 设计为三类 Agent（计划协商、今日复盘、启发式答疑）共享一个 AI Runtime，而非三份独立记忆。
- 业务主表继续是领域状态的唯一事实来源；建议以 Transactional Outbox 追加 `learning_events` 作为供 AI 上下文、异步理解和审计使用的不可变事实流水，不将 Event Sourcing 替换为现有业务表。
- 学生理解以带证据、置信度、有效期和状态的 `DerivedSignal` 保存。模型可提出候选，但不能直接把猜测写成事实或长期画像。
- 保留既有三层学生记忆：Redis 工作记忆、PostgreSQL 近期事件记忆与长期画像；新增的“程序记忆”归为非学生数据的版本化 Skill/Policy Registry，运行中不可自动改写。
- `ContextEnvelope` 是每次模型调用生成的最小证据工作包；各 Agent 用 ContextSpec 限定事实、信号、记忆、Skill 和工具范围，不传完整学生档案。
