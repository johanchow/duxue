# Agent 与 Workflow 配置设计

> 状态：配置与运行适配迁移已实现；领域 Port 通过解包适配保持原调用协议。配置入口见[目录说明](../../duxue-server/agent_specs/README.md)，当前运行图见[现状流程图](agent-flow-current.md)。
> 关联：[项目 DDD 约定](../../.cursor/skills/domain-driven-design/SKILL.md) · [Companion 编排](domain-companion.md) · [当前模型组件注册表](../../duxue-server/app/infrastructure/ai/components.py)

## 一、目标与边界

目标：

- **统一查看**：在同一目录中查看 Workflow、Agent、Gate、Tool 的数量、职责、引用关系与版本。
- **配置即运行依据**：模型参数、Prompt、工具权限和流程结构各有唯一配置来源，运行时加载并校验引用。
- **流程可视化**：由执行所用的定义生成[独立流程图](agent-flow-current.md)，定位节点、条件边、门禁和失败路径。
- **版本可追溯**：稳定 ID 与版本随 Trace 记录，便于定位和复现问题、审阅配置变更。
- **保持业务边界**：配置只描述运行装配；授权、领域规则、状态写入和事务仍由相应代码负责。

本期只随代码发布本地配置；**不做 A/B 实验、在线分流或配置管理台**，也不做远程配置和独立发布链路。配置不得包含任意可执行代码，也不得关闭必经门禁；答案保护和失败安全仍由代码强制。模型输出只是候选，不能直接写入业务事实。

## 二、概念与责任

| 概念 | 定义 | 引用关系与边界 |
| --- | --- | --- |
| Workflow | 一项入口业务流程的编排，声明节点、条件边、重试上限与出口；例如 Companion 路由或 Tutoring Turn | 引用 Agent、Gate 和必要的代码步骤；不直接引用 Tool，不代替领域 Use Case |
| Agent | 承担一个明确任务、遵守类型化输入输出契约的可调用单元 | 由模型或固定代码实现；模型 Agent 声明可用 Tool，Prompt 属于使用它的 Agent |
| Gate | 决定候选能否继续、重试、降级或退出的裁决点 | 由固定代码或独立模型 Judge 实现；多个 Gate 的顺序和条件由 Workflow 编排 |
| Tool | 模型 Agent 或 Judge Gate 在受限执行期间可调用的能力 | 定义名称、用途和参数契约；执行函数、数据授权与副作用边界由代码持有 |
| 代码步骤 | Workflow 内的确定性处理，如准备草稿、写入已确认结果 | 若不独立承担任务，不称为 Agent；只在有复用或管理需求时再抽成独立定义 |

“Agent”按职责划分，不按是否调用模型划分。纯固定代码单元若对外承担完整任务并遵守 Agent 契约，放在 `agents/` 且声明 `implementation: "code"`；单纯的通过/拒绝检查放在 `gates/`。模型 Judge 若负责裁决，也放在 `gates/`，模型与 Prompt 随 Gate 定义。这样不会把答疑泄露 Judge 重复登记为一个 Agent 和一个 Gate。

## 三、目录和命名规范

```text
duxue-server/agent_specs/
├── workflows/             # 一个 Workflow 一个 JSON
│   ├── companion.json
│   ├── planning.json
│   ├── tutoring.json
│   ├── reflection.json
│   ├── task-intake.json       # 独立 API 入口，单 Agent Workflow
│   └── review-aspects.json    # 独立 API 入口，单 Agent Workflow
├── agents/                # 任务单元；模型、Prompt、变量与工具权限
├── gates/                 # 裁决点；实现方式、必经规则和失败处理
├── tools/                 # 工具契约；处理器只使用代码注册的 ID
└── README.md              # 校验、生成图和发布操作
```

目录表达对象类别，文件名使用稳定的业务 ID（例如 `agents/planning.task-intake.json`）；各文件显式声明 `id`、`version`、`kind`，Agent、Gate、Tool 再按各自契约声明输入与结果 Schema。Workflow 用 ID 引用对象，引用必须在启动时解析且唯一。重命名 ID 属于兼容性变更，必须迁移引用和历史观测映射；修改 Prompt、模型、工具权限或输入输出契约应提升相应版本。密钥、环境端点与儿童数据不进入配置。

Prompt 默认**内嵌在使用它的 Agent 或模型 Gate JSON**，不设必需的 `prompts/` 目录。主模型与备用模型可在同一任务单元内共用 Prompt；只有出现真实的跨单元复用，才引入可引用的共享模板，避免正文复制。

## 四、配置契约

以下是**目标 JSON 契约**，用于后续迁移，不是当前 `agent_specs/*.json` 已支持的字段。所有文件禁止未知字段；`id` 在全目录唯一，`version` 使用 `v1`、`v2` 等递增值，`kind` 必须与所在目录一致。输入使用 `input_schema`，Agent/Tool 结果使用 `output_schema`，Gate 裁决使用 `verdict_schema`；这些字段采用受限 JSON Schema（顶层 `object`，明确 `required` 与 `additionalProperties: false`）。运行时先按 JSON Schema 校验，再调用该 ID 在代码注册表中绑定的 Python 契约校验器；两者都必须通过，缺失 Python 契约时启动失败。测试用同一批合法/非法样本检查两层契约的结果一致，防止手工维护的 Schema 漂移。领域对象与业务不变量仍由代码持有。

### 4.1 Workflow 契约

Workflow 文件的 `kind` 固定为 `workflow`。`nodes[]` 的 `kind` 只允许 `agent`、`gate`、`action`；`agent` 和 `gate` 节点必须有 `ref` 指向对应目录的 ID，`action` 必须有代码注册的 `handler_id`，三者互斥。Workflow **没有 `tools` 字段**。`edges[]` 声明 `from`、`to` 和可选 `condition_id`；条件 ID 由受控代码计算，不能写表达式。通用执行器读取节点和边、维护状态与重试预算，调用代码注册的处理器和条件函数，并按条件选择下一节点；JSON 不包含任意表达式。多个 Gate 各占一个 Workflow 节点，由边声明先后、条件分支和出口，不在 Gate 内嵌套子 Gate。`entry` 与所有出口必须可达；`required_gates[]` 的每项声明 Gate ID 和适用条件 `when`（代码注册的条件 ID），启动时与代码安全基线核对，运行时只在条件成立的路径上强制执行。

独立 API 调用也有自己的入口 Workflow：只有一次 Agent 调用时，可定义 `START → Agent → END`。例如 Guardian 任务整理与复盘维度提取分别有独立 Workflow，不把它们假接到 Planning Graph 或 Reflection 会话流程中。

`limits` 属于 Workflow，是**执行次数上限**，不表示模型费用或金额预算。本次迁移保留原实现：`workflows/tutoring.json` 的 `limits.model_calls=4`、`limits.tool_calls=3`。具体语义如下：

| 字段 | 计数范围 | 到达上限后的行为 |
| --- | --- | --- |
| `model_calls` | 每次 `call_tutor_model` 生成尝试内的模型调用；包括返回工具请求的调用和结构修复调用 | 停止当前生成循环；已有可用候选时保留，否则进入原有失败回退 |
| `tool_calls` | 同一次生成尝试内执行的模型工具请求；未知工具请求同样计数，预加载 SVG 规范不计入 | 后续请求不执行工具，返回 `budget_exhausted` 观察结果；仍受模型调用上限约束 |

计数不会跨生成尝试累计。外层泄露修复、备用模型切换、配图修复的触发与次数由 `tutoring-retry` Workflow 条件路径控制，每个新尝试重新计数。配置只能降低代码允许的上限，不得提高；无效配置在启动时拒绝。通用执行器自身另有 32 步执行上限。模型输出 Token 上限、单次超时分别由 `models[].max_output_tokens`、`models[].timeout_ms` 表达，与这些循环次数分开。

例如两个 Gate 的连线在 Workflow 中这样表达（JSON 节选，省略入口和其他节点；`END` 的成功或拒绝状态由已执行 Gate 的裁决确定）：

```json
{
  "nodes": [
    {"id": "authority", "kind": "gate", "ref": "tutoring.authority"},
    {"id": "text_leak", "kind": "gate", "ref": "tutoring.text-leak"}
  ],
  "edges": [
    {"from": "authority", "to": "text_leak", "condition_id": "allow_and_requires_leak_check"},
    {"from": "authority", "to": "END", "condition_id": "allow_and_no_leak_check"},
    {"from": "text_leak", "to": "END", "condition_id": "allow"},
    {"from": "text_leak", "to": "END", "condition_id": "deny"},
    {"from": "authority", "to": "END", "condition_id": "deny"}
  ],
  "required_gates": [
    {"ref": "tutoring.authority", "when": "has_candidate"},
    {"ref": "tutoring.text-leak", "when": "authorized_candidate_requires_leak_check"}
  ]
}
```

### 4.2 Agent 契约

Agent 文件的 `kind` 固定为 `agent`。每个 Agent 均声明 `id`、`version`、`implementation`、`input_schema`、`output_schema` 和闭集 `error_codes`。`llm` Agent 必须声明 `tools`（Tool ID 数组，可为 `[]`）；`code` Agent 不声明 `tools`。循环次数 `limits` 由 Workflow 持有，见 4.1。Agent 返回统一的 `status`（`ok`、`needs_input`、`failed`）、经 `output_schema` 验证的 `data`，以及失败时的受控 `error_code`；Workflow 只接收验证后的结果。

`ok` 表示 `data` 已通过校验；`needs_input` 表示还缺用户输入，`data` 只包含由输出 Schema 允许的追问信息；`failed` 必须有 `error_code`，不可携带未经校验的模型候选。错误码为 Agent 定义中的闭集枚举，不能把提供商异常原文直接返回给 Workflow 或用户。

统一结果由 `schemas/agent-result.json` 与 Python `AgentResult` 双层校验，封套由运行适配器生成，模型仍输出原有候选协议。既有领域 Port 通过解包适配保持原返回值及异常。代码 Agent 返回合法 `WorkflowOutcome` 时，领域的失败状态仍属于已验证的业务数据；只有 Agent 执行本身失败才属于封套的 `failed`，两者不相互替代。

| `implementation` | 何时使用 | 必填字段 | 禁止字段 |
| --- | --- | --- | --- |
| `llm` | 任务由模型生成候选，通用 Gateway 完成调用 | `models`、`prompt`、`context_builder_id`、`tools`（可为 `[]`） | `handler_id` |
| `code` | 固定代码独立完成任务并返回 Agent 契约 | `handler_id` | `models`、`prompt`、`context_builder_id`、`tools` |

`models` 是非空数组，**数组顺序就是模型尝试顺序**：首次从下标 0 开始，只有 Workflow 的已声明重试/切换条件成立时才推进到下一项，不跳过或重排。数组顺序不表示每次请求都要尝试全部模型；同一模型的结构修复次数也由 Workflow 的预算与条件边控制。每次尝试记录模型下标、结果和切换原因，候选都经过相同的 Python 契约与必经 Gate。每项模型声明 `name`、`temperature`、`max_output_tokens`、`timeout_ms`，均受代码安全上限约束；备用模型沿用同一 Agent 的 Prompt 与输出契约。`handler_id` 只是白名单键，不是模块路径。`code` Agent 可以通过受权 Command 完成业务操作，但不能绕过领域规则直接修改 Aggregate。

`context_builder_id` 对 `llm` Agent **必填**。它是代码注册表中的稳定 ID，指定本次模型调用如何从已授权的输入构造上下文：选取近期对话、筛选 profile/memory、确定图片范围并执行预算与脱敏。运行时先按 ID 调用构造器，再将其类型化结果交给 Prompt 渲染。可复用同一个构造器 ID，但只有在输入范围和授权策略确实相同时才共享；公共的 Thread 窗口选择逻辑可由多个构造器复用，不代表每个模型收到同一包数据。省略或引用未知 ID 在启动时失败；配置不能凭 ID 扩大授权范围。

| 目标注册 ID 示例 | 构造的上下文 |
| --- | --- |
| `companion.intent_context` | 本轮输入与近期 Thread 原句窗口；不因路由需要而自动加入 profile/memory |
| `planning.reply_context` | 近期窗口、受权任务以及按计划用途筛选的 profile/memory |
| `tutoring.leak_judge_context` | 待审候选、答疑许可和已选定的受权题图；不继承答疑 Agent 的全部上下文 |

例如任务整理 Agent 的动态 Prompt 可以这样声明变量（示意字段，待迁移时由 Schema 固化）：

```json
{
  "id": "planning.task-intake",
  "version": "v2",
  "kind": "agent",
  "implementation": "llm",
  "error_codes": ["invalid_model_candidate", "model_transport_error", "model_provider_disabled", "model_provider_not_configured", "agent_execution_failed"],
  "input_schema": {"type": "object", "properties": {"request": {"type": "object"}}, "required": ["request"], "additionalProperties": false},
  "output_schema": {"type": "object", "properties": {"tasks": {"type": "array"}}, "required": ["tasks"], "additionalProperties": false},
  "models": [{"name": "qwen3.7-plus-2026-05-26", "temperature": 0, "max_output_tokens": 1600, "timeout_ms": 60000}],
  "context_builder_id": "task_intake.authorized_context",
  "prompt": {
    "template": "今天是 {{today}}。可分配的孩子：{{authorized_wards}}。当前候选：{{candidate_tasks}}。对话：{{conversation_history}}。",
    "variables": {
      "today": {"type": "date", "binding": "context.today"},
      "authorized_wards": {"type": "array", "binding": "context.authorized_wards"},
      "candidate_tasks": {"type": "array", "binding": "context.candidate_tasks"},
      "conversation_history": {"type": "array", "binding": "context.conversation_history"}
    }
  },
  "tools": []
}
```

Context Builder 负责**取哪些数据以及能否读取**；`prompt.variables.binding` 只负责**把构造器输出的哪个字段填入哪个占位符**，不得再次查询数据库或执行表达式。变量由该调用的类型化输入契约和构造器输出显式选择，不能从模板文字或数据库字段自动推断。每项还需定义大小上限和序列化方式；启动时校验占位符、变量声明与构造器输出契约一致，调用时校验类型、范围和缺失值。本轮消息若作为独立 user 内容发送，不重复塞进模板变量。当前 `task.intake` 与 `planning.intake` 的动态 `_prompt` 需要按此原则拆分固定话术和数据组装。

### 4.3 Gate 契约

Gate 文件的 `kind` 固定为 `gate`。每个 Gate 均声明 `id`、`version`、`implementation`、`input_schema`、`verdict_schema`、`on_error` 和 `safety_class`。`judge` Gate 还必须声明 `tools`（Tool ID 数组，可为 `[]`）；`code` Gate 不声明 `tools`。统一裁决值 `verdict` 只允许 `allow`、`deny`、`unknown`；`reason_code` 使用该 Gate 声明的闭集枚举。`unknown` 和执行异常**不能当作 `allow`**。重试或结束由 Workflow 根据裁决和已声明条件边决定，不由 Gate 自行写业务状态。

| `implementation` | 何时使用 | 必填字段 | 禁止字段 |
| --- | --- | --- | --- |
| `code` | 确定性协议、权限或领域前置检查 | `handler_id` | `models`、`prompt`、`context_builder_id`、`tools` |
| `judge` | 独立模型审查语义化候选 | `models`、`prompt`、`context_builder_id`、`tools`（可为 `[]`） | `handler_id` |

`safety_class` 只允许 `protected`、`standard`。`on_error` 只允许 `deny`、`abort`、`drop_optional_output`；每个 Gate 的可用值还须经代码白名单约束，例如只检查可选配图的 Gate 才能选择 `drop_optional_output`。`protected` Gate 的失败策略不得由配置放宽。Gate 只完成自己的裁决，不声明子 Gate 或执行顺序。Gate 的必经性属于 Workflow 使用处，由 `required_gates[].when` 与代码安全基线共同约束；条件不成立时允许跳过，条件成立却未经过该 Gate 时执行器必须拒绝结束。

`judge` 的 `models`、`prompt`、`context_builder_id` 与模型 Agent 使用同一字段契约。Judge 的构造器只取本次候选、裁决依据和必要的受权证据；需要原图或限定历史时使用相应的专用构造器，不因 Agent 已看到 profile/memory 就自动继承。即使只需要候选本身，也明确引用一个最小构造器 ID。统一 `verdict_schema` 至少包含 `verdict` 和 `reason_code`，各 Gate 在此基础上收紧原因码。模型返回无法解析时也视为 `unknown`，再按 `on_error` 处理。

例如固定代码的越权检查（示意字段，非已上线 Schema）：

```json
{
  "id": "tutoring.authority",
  "version": "v1",
  "kind": "gate",
  "implementation": "code",
  "handler_id": "tutoring.check_authority",
  "safety_class": "protected",
  "on_error": "deny",
  "input_schema": {"type": "object", "properties": {"candidate": {"type": "object"}, "permit": {"type": "object"}}, "required": ["candidate", "permit"], "additionalProperties": false},
  "verdict_schema": {"type": "object", "properties": {"verdict": {"enum": ["allow", "deny", "unknown"]}, "reason_code": {"enum": ["ok", "no_permit", "invalid_candidate", "check_error"]}}, "required": ["verdict", "reason_code"], "additionalProperties": false}
}
```

答案泄露检查是 `judge` Gate，其模型与 Prompt 放在该 Gate 内，并显式声明 `"tools": []`。答疑出口需要越权、答案泄露等多个 Gate 时，Workflow 分别引用它们并声明条件边；不存在综合型 Gate 定义。

### 4.4 Tool 契约

Tool 文件的 `kind` 固定为 `tool`，声明 `id`、`version`、`description`、`input_schema`、`output_schema`、`handler_id` 和 `access`（`read` 或 `write`）。`llm` Agent 或 `judge` Gate 的 `tools` 数组是其唯一可调用清单；Workflow 不直接引用 Tool。`handler_id` 必须命中代码注册表，处理器负责 Ward 授权、数据范围和副作用。工具调用次数上限由 Workflow 的 `limits.tool_calls` 与代码上限共同约束，计数范围见 4.1。

## 五、执行、领域边界与观测

启动时校验文件 Schema、ID 唯一性、引用、Workflow 可达性、处理器白名单、模型及工具预算、条件 Gate 与安全失败策略。通用执行器从 Workflow 定义装配控制流；处理器、条件函数、授权和领域写入仍由代码负责。迁移时用现有离线评测重放模型行为，并用单元与集成测试覆盖重试次数、条件 Gate、失败安全、确认恢复和事务边界。Workflow 装配和 Agent/Gate/Tool 查找都使用同一目录；流程图也从它生成。配置改动与代码、评测和文档同一 PR 审阅并发布；本期每个稳定 ID 只有一个生效版本，不引入分流规则。

按项目当前 DDD 约定，Domain 是拥有业务语义、模型和规则的边界；Workflow 和 Agent 是 Application/Infrastructure 的运行角色，不是新的 Domain 或 Aggregate。Companion 只维护 Thread/Run 连续性并路由受权调用；Planning、Tutoring、Evaluation 各自裁决并写入自己的业务状态。配置目录集中的是**运行描述**，不是跨 Domain 的共享业务模型。装配器应处于应用组合层，领域模块不读取配置，也不依赖模型或工具实现。

Trace 中的 Workflow/Agent/Gate/Tool 均记录稳定 ID、配置版本、节点 ID、结果和受控耗时指标，便于从 Grafana、Langfuse 回到具体定义。Prompt 变量与工具结果按现有儿童数据策略脱敏；配置、图和观测统计不能替代业务审计或学习事实。
