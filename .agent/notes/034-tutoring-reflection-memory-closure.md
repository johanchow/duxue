# 答疑、复盘与 Memory 闭环

- 答疑工作流把 Ward 尝试（或理解确认）、每次实际给出的提示及会话关闭分别写为版本化 `LearningFactRecorded.v1`；这些事实与 Outbox 在同一事务中写入。直接索答仍只返回苏格拉底式首步。
- `tutoring_episode` 只在收到关闭事实后结算，并关联全部受控答疑事实；它不读取或复制 `tutoring_messages` 的原始内容。重复结算复用 `memory_type + aggregate_ref + aggregate_version` 和证据链接唯一键。
- Memory Worker 消费 Outbox 时只幂等入账，不重新发布来源事实。关闭事实触发 episode 结算；Signal 的候选、激活/到期及 Profile 重建保持独立的受控 Worker 路径。
- 长期 Signal 的 v1 激活门槛是 `long_term`、置信度至少 0.75、至少两条支持证据；Ward challenge 会追加反证并使其退出 Profile 投影。后续产品调整门槛时应提升 `policy_version`，不要在模型提示中隐式改变。
- Reflection 允许在已有自评上以显式 `adopt_focus_kit` 单独采纳行动；不会因为仅采纳动作而再写一份自评事实。
