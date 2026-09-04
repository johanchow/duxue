# Agent 执行模式：工作流与受限 ReAct

- 计划协商和今日复盘采用显式状态图：它们的阶段、事实快照、确认写入和终止条件均是确定性的业务规则，模型只处理自然语言理解、追问、归纳和解释。
- 计划协商的 Graph 固定为：识别本次意图（不清晰则追问）→ 校验本次意图的可执行性 → 检查剩余任务的时间冲突和待排期确认项 → 确定性排程、Ward 审阅和确认。每个协商节点可以有等待 Ward 输入的有界局部循环；确认提交前必须重新以最新版本校验全局约束。
- 启发式答疑不采用固定教学 Graph，而是“持久化会话生命周期 + 动态 `TutorWorkingState` + 受限 ReAct”。`L1`～`L4` 是 Policy 中解释粒度的建议与上限；模型按每轮上下文选择苏格拉底式教学动作，不能自行形成能力标签或改写长期画像。
- 答疑动作分为教学动作、Tool Call 与会话指令三个层次；每轮有固定步数和工具预算，工具与工作状态 patch 均经 Runtime 校验并写入 Trace。领域服务只记录 Ward 尝试、实际提示、检索和会话结算等事实。
- 答疑会话结束后，Worker 将有关事实事件结算为 `episodic_memories[event_type=tutoring_episode]`，并以证据关联支持后续按知识点、未解决状态和有效策略的最小化召回；不复制完整聊天记录，也不将单次卡点升级为长期结论。
- 统一入口采用 `Companion Coordinator`，而不是可自由委派的 Supervisor Agent。它按安全、UI 上下文、活跃会话、明确意图、低置信度分类和澄清的固定优先级路由到一个领域 Agent；不生成领域答案、不调用业务工具、不读取完整记忆、不写业务事实。跨 Agent 通过 Ward 确认的受控 Handoff 和最小 `context_refs` 完成。
- 文档边界已拆分：`docs/technical/design-memory.md` 是事实账本、Signal、三层记忆、表映射、更新/衰减与删除策略的唯一事实源；`docs/technical/design-agent.md` 是入口路由、三个 Agent 控制模型、Runtime、Policy、Context 与写回协议的唯一事实源。两文档只通过链接交叉引用，不复制对方详细设计。
- Memory 访问使用同进程 `MemoryFacade`，而非 Agent 直接查表或面向 App 的公开 API。`resolve_context(MemoryContextRequest)` 是 Agent 唯一聚合读入口；工作记忆、情境记忆、Signal 和 Profile 的专用查询仅允许鉴权后的领域服务使用。事实写入、情境结算、Signal 演进和 Profile 重算属于独立的 Worker/领域服务写接口，模型无权调用。
- 三层 Ward Memory 的术语已澄清：`learning_events` 是事实证据底座，不计为记忆层；Working Memory、Episodic Memory、Semantic Memory 构成三层。`DerivedSignal` 是第三层的证据化规范来源，`LongTermProfile` 只是 Active 长期 Signal 的可重算聚合投影，不是独立第四层或可写事实源。
- 该决策已补充到 `docs/technical/design-memory.md`，作为后续 `ai_agents` 与 `ai_runtime` 的实现边界。
