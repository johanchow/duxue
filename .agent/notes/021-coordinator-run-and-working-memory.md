# Coordinator Run 与工作记忆更新边界

- 同一个 `ConversationThread` 可以关联多个先后发生的 Planning、Tutoring 与 Reflection Run；`focus_run_ref` 仅是普通追问的默认承接对象，不能覆盖 Ward 明确提出的新领域意图。跨领域转换经 Ward 确认的 Handoff 执行；每轮只允许一个领域 Agent 拥有回复权。
- Coordinator 仅管理线程定位、Run 引用、路由决定和 Trace；不保存任一领域工作状态、完整聊天上下文或完整 Ward Memory。目标 Agent 按自身 ContextSpec 和最小 `context_refs` 重建上下文。
- Working Memory 是“确定性业务状态 + 已验证交互/工具事实 + 受预算约束的少量会话摘要”的可校正运行状态，不等同于对话总结。它在会话开始/恢复、每轮交互、实际提示或工具结果、草稿变更和会话结束等状态变化点增量归约；会话结算后才异步生成 Episodic Memory。
- `dialogue_summary` 只用于压缩较早对话：近期关键记录保留，超过版本化条数/token 阈值才压缩。模型只能提出 patch/摘要候选，Runtime 与领域规则负责来源、Schema、权限和 Policy 校验。
