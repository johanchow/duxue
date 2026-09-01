# 记忆证据链与长期画像投影

- `learning_events` 是 AI 记忆系统的不可变事实根；领域业务主表仍是各自业务状态的唯一事实来源。
- `episodic_memories` 是近期可召回摘要，通过 `episodic_memory_events` 关联多个事实事件，不能只保存一个来源事件 ID。
- `derived_signals` 保存可校正的理解主张，而非事实或永久画像；它必须有状态、置信度、有效期、规则版本，并通过 `derived_signal_events` 保存支持、反证和 Ward 确认事件。
- `long_term_profiles` 保持每 Ward 一行，但定位为 Active 长期 Signal 的物化读模型：每日完整重算并覆盖旧快照，不直接追加事件证据。
- 长期画像顶层维度保持有限且受控：专注基线、知识卡点、稳定兴趣、有效策略、计划偏好、自我调节、学习节律与明确沟通偏好。详细 `signal_type` / `value` Schema 只维护在 `docs/technical/design-memory.md`。
- 2026-08-30 实施：学习/任务/会话/记忆域改用 PostgreSQL 原生 UUID；`tasks` 合并原 assignments 与 plan items；`study_session_intervals` 保留每次暂停/恢复。陪学对话由 `tutoring_sessions`/`tutoring_messages` 承载，帧和行为片段可选关联执行会话。
- 事件在同一事务写入 `learning_events` 与 `outbox_events`，以来源四元组幂等；异步消费者负责再生成 episodic memory、signals 和 long-term profile。所有新外键保持数据库默认 `NO ACTION`，删除由应用级受控工作流执行。
- 2026-08-30 文档收敛：用户与绑定按当前 `users`、角色资料扩展、`guardian_ward_relations` 和 Ward 登录邀请码表描述；计划域按当前 `daily_schedules` 与 `tasks` 的物理字段描述，不将尚未实现的共管邀请、计划主题、任务学科/优先级字段写作现状。
