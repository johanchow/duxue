# Agent 定义目录

`workflows/` 存放流程；`agents/` 存放模型、Prompt、动态变量和工具权限；`gates/` 存放 Judge 与代码门禁；`tools/` 存放工具契约与处理器 ID。模型参数和 Prompt 正文的唯一来源已经迁入 JSON，Python 保留调用适配器与契约校验。`models` 数组顺序就是尝试顺序，是否切换仍由运行流程决定。

节点实现、路由条件、权限、答案保护、事务和失败回退仍由 Python 负责。JSON 不支持任意函数、表达式或在线修改。Planning 的 LangGraph 边从 JSON 装配；任务整理、复盘维度提取、答疑候选审核由通用执行器驱动。候选审核中授权、文字与配图检查各占一个 Gate，适用条件与必经基线受代码校验。

模型调用先检查 JSON Schema，再检查 Python 输出契约；错误结果进入原有的修复或失败回退。动态 Prompt 使用显式变量声明和一次性替换。任务整理与复盘维度提取各有自己的单 Agent Workflow。

Companion 主路由、答疑重试与主备切换已由通用执行器读取条件边；Planning 确认门禁作为独立 LangGraph 节点执行，等待用户确认的节点只接收命令。10 个模型调用通过配置中的 `context_builder_id` 执行专用构造器；构造器只投影调用方已授权的数据，不能自行扩大读取范围。

Workflow 节点统一为 `agent/gate/action`，代码步骤使用 `handler_id`，条件边使用 `condition_id`；原 route/stage/check 标识只作为 `trace_kind` 观测信息。代码注册表在启动时拒绝未知处理器、条件和对象引用。领域入口的代码 Agent 在 `agents/*.session-turn.json` 声明 `RunInvocation/WorkflowOutcome` 契约，Dispatcher 执行 JSON Schema 与 Python 双层校验。

Judge 的 `provider_output_schema` 描述模型原始协议，`verdict_schema` 描述适配后的 `allow/deny/unknown` 与 `reason_code`。Agent 使用 `status/data/error_code` 结果封套，由 `schemas/agent-result.json` 和 Python 契约共同验证；现有领域 Port 通过解包适配保持原返回协议，封套由代码生成，不改变模型输出 Prompt。

答疑循环按原实现保留 `workflows/tutoring.json` 的 `limits.model_calls=4`、`limits.tool_calls=3`，表示每次生成尝试内的调用次数，不是金额。工具请求和结构修复都计入模型调用次数，外层重试另由 Workflow 条件路径控制。字段归属与到限行为见[设计契约 4.1](../../docs/technical/design-agent.md)。进度与验收见 [迁移 spec](../../.agent/specs/done/agent-runtime-contracts.md)。

```bash
cd duxue-server
.venv/bin/python -m app.agent_specs validate
.venv/bin/python -m app.agent_specs show companion
.venv/bin/python -m app.agent_specs export
```

`show` 输出展开的组件模型、Prompt 和契约；`export` 生成独立的[当前流程图](../../docs/technical/agent-flow-current.md)。改定义后应提交生成图，测试会检查同步。目标目录、字段契约与概念划分以 [Agent 配置设计](../../docs/technical/design-agent.md) 为准。
