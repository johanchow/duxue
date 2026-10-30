# Agent 结构定义与代码边界

提交前检查补充：PlanningAdapter.invoke 的 invocation 为 keyword-only，统一 Dispatcher 必须使用 invoke(invocation=invocation)，不能传位置参数；已新增独立回归测试，配置契约测试 29 项通过。

以下前半部分记录初始阶段；最新迁移状态以文末链接的 spec 和配置目录 README 为准。

Companion、Planning、Tutoring、Reflection 的节点、组件引用、工具、门禁和主要条件边统一放在 `duxue-server/agent_specs/*.json`。运行时加载并校验，Planning Graph 的节点与连线从定义装配，图由同一份定义生成。模型和 Prompt 参数继续以 `components.py`、`prompts.py` 为唯一事实源；JSON 引用组件 ID，不复制 Prompt。

安全裁决仍在 Python：JSON 不能提供可执行 handler、取消强制门禁、扩大工具集合或提高预算。`planning.task_intake` 和 `reflection.review_aspects` 是独立 API 调用，不能画成 Planning Graph 或 Reflection 会话的内部节点。

经验：静态流程图容易把相关调用误画成串行调用；定义与实际跨度要分清。新增节点时同时登记 `trace` 和组件引用，并运行目录校验、图生成同步测试及服务端测试。

后续概念划分、目标目录与字段契约统一记录在 [`docs/technical/design-agent.md`](../../docs/technical/design-agent.md)：Workflow 只编排 Agent/Gate/代码步骤，Agent 才引用 Tool；Prompt 内嵌于使用它的 Agent 或模型 Gate。现状图由同目录的 `agent-flow-current.md` 独立生成，设计文档不嵌入运行快照。

文档中的 DDD 边界术语以当前 `.cursor/skills/domain-driven-design/SKILL.md` 为准：使用 Domain 表示业务边界，不再引入 Bounded Context 作为第二层边界。

目标契约明确了 Agent 的 `llm/code` 与 Gate 的 `code/judge`；多个 Gate 由 Workflow 连线。`tools` 是 `llm` Agent 与 `judge` Gate 的必填数组，允许为空；固定代码单元不声明工具。Gate 的必经性归 Workflow 使用处，`unknown` 不能放行。现状图移到独立文件，具体字段值见链接文档。

`context_builder_id` 对 `llm` Agent 和 `judge` Gate 均必填：它选择代码注册的受权上下文构造器；Prompt 变量只绑定该构造器的输出字段。多个构造器可复用同一近期对话窗口选择逻辑，但各调用不继承同一包 profile/memory；Judge 只取裁决所需证据。

用户明确本期不做 A/B 实验或配置管理台，并要求移除旧的 `infra-ai-components.md`。目标配置设计以 `design-agent.md` 为唯一文档；当前组件注册与 Prompt 以 `components.py`、`prompts.py` 为准。历史 spec 中对旧文档的文字引用保留为当时记录。

实现前的契约决策：保留 JSON Schema 描述文件输入/输出，并为每个 ID 注册 Python 契约校验器；启动时检查两层契约及引用，测试用同一批正反例防止漂移。Workflow 目标是由通用执行器解释节点、条件边和预算；条件通过代码注册 ID 计算，Gate 必经性按适用条件核对。模型 `models` 数组顺序就是尝试顺序，只有声明的切换条件成立才推进。独立的任务整理与复盘维度 API 各用自己的单 Agent Workflow 表示。迁移的重点测试是答疑重试与 Gate 复检、失败安全、Planning 中断恢复和事务边界；现有目标方案尚未落地，不能把文档字段当作当前运行能力。

目录与运行契约迁移已开始，后续完成度统一记录在 [agent-runtime-contracts spec](../specs/done/agent-runtime-contracts.md)。模型参数和 Prompt 正文已经迁入 JSON，动态模板只做一次替换，避免用户文本中的占位符被再次解析。答疑审核已使用条件 Workflow，主路由、确认恢复、重试外层及真正的 Context Builder 调度仍待迁移；不可把当前部分落地标为完整目标实现。

继续迁移：主路由和答疑重试已由条件 Workflow 驱动；Planning 确认门禁拆成独立持久化 Graph 节点；Context Builder 已实际按配置 ID 执行。构造器签名显式限定输入，Judge 不接收 Agent 的 profile/history；构造器不查询额外业务数据。剩余契约清理由上述 spec 跟踪。

节点类型与 Trace 类型已经分离；route/check/stage 是 trace_kind，执行节点只用 agent/gate/action。Judge 模型的旧 leaks/allow_switch 协议用 provider_output_schema 单独描述，经 Python 适配和标准 verdict_schema 检查后使用。代码 Agent 的领域兼容返回使用 WorkflowOutcome，尚未整体切到目标 Agent 结果封套；不能据此宣称完整目标契约已经完成。

迁移收尾：AgentResult 封套已用于模型 Agent、代码 Agent 和通用执行器；由 JSON Schema 与 Python 同时检查 failed 不携带候选、成功必须有 data、错误码闭集等不变量，既有 Port 通过解包适配保留原返回值与异常。用户明确循环次数上限必须保留；没有删除 MAX_TOOL_CALLS 或改变计数。Workflow 的 limits 是每次生成尝试的 4 次模型调用、3 次工具请求，外层修复另计，均不是费用预算；契约归属以 design-agent.md 4.1 为准。696 项测试与配置/静态检查通过，未执行真实模型 API 评测。用户已要求提交，spec 已归档。
