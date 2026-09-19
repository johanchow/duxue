# Agent Design Skill：按控制模式分层的约束

日期：2026-09-19

- 更新通用 `agent-design` skill 时，新增规则按适用模式分层：所有模型辅助模式共享“语义候选 + 确定性决议”“失败不可伪装为成功”“物质性动作 capability”等原则；可恢复 Workflow/Hybrid 额外要求固定 ExecutionScope 与 resume preflight；有界 Agent Loop 额外要求预算、停止条件与确定性完成验证。
- 时间、locale 等不是项目条件，而是在影响用户可见语义时纳入稳定 ExecutionScope 的一般规则。
- 入口 `SKILL.md` 只保留模式路由和通用原则；Workflow/Hybrid 细节下沉到 `references/workflow-runtime.md`，Loop/Hybrid 细节下沉到 `references/agent-loop-runtime.md`。这避免普通结构化调用加载不适用的 checkpoint 或循环约束。
- 更新同步落在入口、模式选择框架、审查清单和设计模板，避免只增加原则却没有可执行的设计产物或验收项。
