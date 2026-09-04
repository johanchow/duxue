# 读学系统 — 陪伴 Agent 技术设计

> 状态：讨论稿
> 版本：v1.0
> 适用范围：`duxue-server` 的统一入口、计划协商、启发式答疑、今日复盘与 AI Runtime
> 关联文档：[孩子理解与记忆技术设计](design-memory.md) · [产品架构](../product/ARCHITECTURE.md) · [协商式计划 PRD](../product/prd-schedule.md) · [陪伴执行 PRD](../product/prd-companion.md) · [结果评估 PRD](../product/prd-evaluate.md) · [服务端详细设计](design-server.md)

## 一、目标与边界

本设计定义 Ward 可感知的三个陪伴能力及其统一入口：

1. **计划协商 Agent**：理解 Ward 本次意图，澄清任务、时长和可用时间，形成由 Ward 确认的计划。
2. **今日复盘 Agent**：先接收 Ward 自评，再基于实际执行、答疑和已到达的行为分析，引导 Ward 理解差异并形成下一步行动。
3. **启发式答疑 Agent**：用苏格拉底式提示、可信资料检索和持续会话状态帮助 Ward 思考，不直接代答或代写。

三个 Agent 共享 `AI Runtime`、版本化 Policy 和 [记忆系统](design-memory.md)，但不是可自由互相委托的多 Agent 网络。跨场景信息只能经领域事实、受权限控制的 Memory 和 Ward 确认的 Handoff 传递。

### 1.1 核心原则

- **Ward 主体性**：AI 只提出建议或草稿；正式计划、反思归因和行动采纳由 Ward 确认。
- **最小上下文**：一次调用只注入当前目标相关的事实、Memory、Signal 和知识资料。
- **业务写入受控**：模型不直接写业务表、事实账本、长期画像或 Policy；所有写入经领域服务、Schema 校验与必要确认。
- **Policy 与 Ward Memory 分离**：专家策略决定 AI 怎样陪伴；记忆记录 AI 已知的 Ward 学习过程。
- **可观测、可回放**：每次运行记录 Context Snapshot、Policy/模型版本、工具摘要、输出和状态变化；不保存模型隐式推理过程。

### 1.2 非目标

- 不使用可自由搜索、自由执行、自由互相委派的通用多 Agent 框架。
- 不允许线上 Agent 修改安全、隐私、反代写或专家教学规则。
- 不将结构化业务计算（时间冲突、排程、权限）交给模型。

## 二、总体架构与控制模型

```text
读学 App · Ward
  → 统一陪伴入口 / Companion Coordinator
      ├─ 计划协商 Agent（显式 Graph）
      ├─ 今日复盘 Agent（事件触发 Workflow）
      └─ 启发式答疑 Agent（会话生命周期 + 受限 ReAct）
                    │
                    ▼
AI Runtime / Context Builder / Model Gateway / Tool Gateway
Policy Registry / Output Validator / Trace
                    │
                    ▼
领域服务 + [记忆系统](design-memory.md)
```

| Agent | 控制模式 | 模型负责 | 领域服务负责 |
|---|---|---|---|
| 计划协商 | 有循环的状态图/工作流 | 理解表达、必要追问、解释草稿 | 任务池、时间约束、确定性排程、确认写入 |
| 今日复盘 | 事件触发工作流 | 支持性提问、归纳、行动建议 | 指标计算、事实对比、报告版本、异步补充 |
| 启发式答疑 | 持久化会话生命周期 + 受限 ReAct | 选择教学动作、诊断当轮卡点、解释 | 安全拦截、工具授权、会话/事实记录、候选理解写入 |

`AgentDefinition` 是 Runtime 的配置与协议，不是拥有业务数据的领域模型。最低包括 `ContextSpec`、控制模型、Policy 标识与版本、工具白名单、token/工具/步数预算、输出 Schema 和终止条件。领域 Checkpoint 使用对应计划/复盘聚合标识或 `ward_id + study_session_id`（答疑）持久化；Redis 保存低延迟工作状态，PostgreSQL 保存可恢复的关键版本与结算状态。

## 三、统一入口：Companion Coordinator

Ward 可以从同一聊天入口提出计划、答疑或复盘请求，但统一入口不等于一个拥有所有状态和工具的总控模型。入口层实现为 **Companion Coordinator**：确定性优先的受控编排/路由组件，不是第四个陪伴 Agent，也不是可自由委派的 Supervisor Agent。

Coordinator 不生成领域答案、不调用业务工具、不读取完整 Ward Memory、不直接写业务事实或长期理解。

```text
POST /companion/turn
  → 鉴权、解析 ConversationThread 与 UI route_hint
  → 安全预检
  → 查找当前活跃领域会话
  → 确定性规则路由
  → 低置信度时一次结构化意图判别
  → 创建 / 恢复一个领域 Agent Run
  → 目标 Agent 依 ContextSpec 装配上下文并 SSE 返回
```

路由优先级固定如下，越靠前越不可被模型覆盖：

1. **安全与权限**：未成年人安全、鉴权失败或越权请求进入安全响应；
2. **显式 UI 上下文**：服务端验证通过的 `route_hint`，如计划页、复盘页、当前学习会话；
3. **活跃领域会话的正常续接**：例如活跃答疑中的普通追问默认继续答疑；活跃会话只是默认承接对象，不能覆盖 Ward 明确提出的新领域意图；
4. **明确表达的意图**：如“帮我排明天”“这题不会”“我想复盘今天”；
5. **一次轻量结构化分类**：仅当前述规则无法判定时，分类到有限目标或返回澄清；
6. **澄清**：置信度不足或并列多意图时，只问 Ward 本轮希望先处理哪件事，不擅自启动多个领域流程。

```python
class RouteDecision(BaseModel):
    target: Literal["planning", "tutoring", "reflection", "clarify", "safety"]
    mode: Literal["start", "continue", "handoff", "clarify"]
    confidence: float
    active_session_id: UUID | None
    route_reason: str          # Trace 中的可审计依据，不保存隐式推理
    context_refs: list[str]    # 仅 task / session / draft 等受权对象引用
```

轻量分类器只能输出 `RouteDecision`，不能调用模型工具、读写领域数据或直接回复业务内容；规则可以直接覆盖分类结果。`route_reason` 只记录命中的 UI 提示、活跃会话或显式意图等可审计依据。

### 3.1 Coordinator 的最小状态与多个领域 Run

同一个 `ConversationThread` 可以先后关联多个领域 Run，而不是“一条线程只属于一个 Agent”。例如 Ward 可以先协商计划、随后答疑、最后复盘；同一时刻只能有一个领域 Agent 持有本轮回复权。Coordinator 只保存入口编排所需的数据：线程定位、默认承接 Run、Run 引用、路由决定及 Trace；不保存领域工作状态、完整聊天上下文或完整 Ward Memory。

```python
class ConversationThreadState(BaseModel):
    thread_id: UUID
    ward_id: UUID
    focus_run_ref: str | None        # 普通追问的默认承接对象，不是强制路由
    version: int                     # 乐观锁，避免并发 turn 串线

class AgentRunLink(BaseModel):
    thread_id: UUID
    agent_type: Literal["planning", "tutoring", "reflection"]
    run_ref: str                     # plan_draft / tutoring_session / reflection_run 的受权引用
    status: Literal["active", "waiting_for_ward", "paused", "closed", "escalated"]
    started_at: datetime
    last_active_at: datetime
```

`focus_run_ref` 只表示“若本轮输入是该会话的正常续接，应优先恢复哪个 Run”。它不能让 Coordinator 忽略 Ward 的明确新目标。切换领域时，Coordinator 按目标 Run 的生命周期暂停、等待或关闭原 Run，创建/恢复新 Run，并仅携带经过授权的最小 `context_refs`；领域 Agent 之间不得直接互调或复制彼此的完整状态。

因此，活跃 Run 的判定应包含“本轮是否为正常续接”的检查：

```text
安全与权限
  → 有效 route_hint
  → 输入是否为 focus Run 的正常续接？是则 continue
  → 否则识别明确的新领域意图
       → Ward 已确认切换：handoff / start
       → 多个并列或无法判定的意图：clarify
```

例如，活跃答疑中的“我还是不明白第二步”继续答疑；“这题会了，帮我安排明天复习”则在答疑生命周期允许的边界暂停或结算后，受控切换至计划协商。若输入同时包含答疑和计划而 Ward 未指定优先级，Coordinator 必须返回澄清，而非并行执行。

Coordinator 管理入口连续性与路由，不合并不同 Agent 的状态：

```text
ConversationThread：统一聊天入口的消息顺序、路由历史和展示连续性
  ├─ PlanDraft / PlanWorkflowCheckpoint：计划协商专属状态
  ├─ TutoringSession + TutorWorkingState：答疑专属状态
  └─ ReflectionRun + ReportVersion：复盘专属状态

Shared Memory：[LearningEvent / EpisodicMemory / DerivedSignal / LongTermProfile](design-memory.md)
```

`ConversationThread` 不是第四份 Ward 记忆，也不能将完整对话自动转交给下一个 Agent。Coordinator 只传递 `context_refs`；目标 Agent 按自身 ContextSpec、权限和预算重新构造最小上下文。

跨 Agent 的转换采用受控 Handoff。例如答疑结束时 Ward 说“那明天怎样安排复习”，答疑 Agent 只能输出 `handoff_suggestion = planning` 和最小事实引用；Ward 明确确认或点击入口后，Coordinator 才创建 Planning Run。若一个输入同时含答疑和计划意图，默认要求 Ward 选择优先事项；只有 Ward 或 UI 已明确选择时才顺序执行，并且每次只允许一个领域 Agent 持有本轮回复权。

Coordinator 为路由、澄清、Handoff 和 Agent Run 记录 Trace（线程 ID、路由版本、目标、规则/分类依据、上下文引用、Policy/模型版本和耗时）。这些是运行审计数据，不是 [LearningEvent](design-memory.md)；只有领域服务确认发生的 Ward 行为或业务状态才写入事实账本。

## 四、计划协商 Agent：状态图与局部循环

计划协商以 Ward 当前请求为入口、以 Ward 确认的计划变更为出口。它先确认意图是否理解，再确认意图是否可执行，并检查与其他剩余任务和既有约束的兼容性。计划草稿是临时聚合，确认前不得写入 `DailySchedule` 或 `Task` 正式状态。

```text
接收 Ward 输入
  → 识别本次意图（加任务 / 做计划 / 调整计划 / 其他）
      ├─ 意图或必要参数不明确 → 追问并补齐 → 识别本次意图
      └─ 明确
  → 校验本次意图
      ├─ 任务太大、太模糊、不可执行或与指定时间冲突 → 协商拆分/调整 → 校验本次意图
      └─ 通过
  → 全局待办与约束检查
      ├─ 剩余任务与可用时间存在冲突 → 协商取舍/调整 → 全局待办与约束检查
      ├─ 存在待排期确认任务 → 询问本次是否纳入 → 全局待办与约束检查
      └─ 无需处理
  → 确定性排程并生成草稿
  → 展示草稿
      ├─ Ward 修改 → 返回受影响的校验节点
      ├─ Ward 暂存 → 保存未确认草稿并结束
      └─ Ward 确认 → 提交前重校验
                              ├─ 数据/约束已变化 → 全局待办与约束检查
                              └─ 通过 → 领域服务原子提交计划与 Fact Event
```

| Node | 模型可做的事 | 必须由领域服务做的事 |
|---|---|---|
| 识别本次意图 | 分类意图、抽取任务/时长/日期、提出必要追问 | 校验 Ward 身份和草稿归属 |
| 校验本次意图 | 解释“太大/太模糊”，提出拆分或澄清方案 | 判断时段冲突、最小任务字段和时长边界 |
| 全局待办与约束检查 | 中性说明取舍，询问本次处理范围 | 查询权威任务/日程、计算容量与冲突、列出待排期项 |
| 确定性排程 | 解释排程取舍 | 计算可行排期及候选方案；模型不得伪造时间槽 |
| 审阅与确认 | 回答 Ward 对草稿的疑问 | 保存草稿、按确认命令提交正式计划 |

Node 内可以有等待 Ward 输入的有界局部循环，如“追问—补齐参数—重抽取”或“方案—选择—重校验”。Node 返回 `next`、`need_ward_input`、`revise`、`blocked`、`finish` 等结果并携带临时草稿 patch；patch 不等于领域写入。

提交前必须以最新版本重校验：协商期间若其他端更新任务、固定事件或计划，返回全局检查节点说明变化，绝不静默覆盖。通过后由领域服务同事务更新业务主表及 [Fact Event](design-memory.md)。

## 五、启发式答疑 Agent：会话生命周期 + 受限 ReAct

答疑不预设“理解题意 → L1 → L2 → 验证理解”的固定教学 Graph：题型、Ward 表达、已有知识和当轮卡点不可预知。它以持久化**会话生命周期**保障安全和恢复，以动态 `TutorWorkingState` 保存本轮已知情况，并让受限 ReAct 选择苏格拉底式教学动作。`L1`～`L4` 是 Policy 中解释详细度建议与上限，不是不可跳转流程状态。

```text
会话启动 / 恢复
  → 权限、安全与上下文装配
  → ReAct 对话循环
       Ward 输入 / 图片 / 语音
       → 观察 TutorWorkingState 与相关历史情境记忆
       → 选择教学动作和受控工具
       → 工具结果回填、Policy 校验、回复 Ward
       → 更新工作记忆与会话摘要
  → Ward 结束 / 超时 / 转交
  → 领域结算、Fact Event 落账与异步情境记忆提炼
```

固定生命周期状态仅为 `active`、`waiting_for_ward`、`paused`、`closed`、`escalated`；教学状态是可校正工作记忆，不是 Graph 节点：

```python
class TutorWorkingState(BaseModel):
    session_status: Literal["active", "waiting_for_ward", "paused", "closed", "escalated"]
    task_context: dict
    learning_goal: str | None           # 当轮具体目标，不得表述为能力标签
    ward_attempts: list[dict]           # Ward 明确表达或提交的步骤
    demonstrated_understanding: list[dict]
    candidate_stuck_points: list[dict]  # 临时假设，可被后续输入推翻
    dialogue_summary: str
    current_strategy: dict              # 当前引导策略和解释粒度
    support_history: list[dict]
    retrieved_knowledge: list[dict]
    turn_budget: dict
```

模型输出的是教学动作；面向 Ward 的自然语言是动作的结果，不是独立 `reply` 动作。工具调用和会话控制不与教学动作混为一个枚举：

| 类别 | 动作 | 作用 |
|---|---|---|
| 教学动作 | `clarify_problem`、`elicit_attempt`、`surface_reasoning` | 澄清题目与目标，要求 Ward 表达已有尝试和理由 |
| 教学动作 | `focus_attention`、`give_hint`、`reframe_strategy` | 收束到条件/关系，给最小线索或切换表示方法 |
| 教学动作 | `test_understanding`、`correct_misconception`、`explain_concept` | 验证理解、温和纠正具体推理，或在尝试后补充概念 |
| 教学动作 | `encourage_reflection`、`manage_learning`、`close_session` | 归纳有效策略，处理疲劳/挫败/求助，或总结本轮 |
| Tool Call | `curriculum_retrieval`、`image_question_parser`、可选确定性 `attempt_checker` | 获取受控资料、解析题图或辅助核验；不替代教学决策 |
| 会话指令 | `continue`、`wait_for_ward`、`pause`、`close`、`escalate` | 控制生命周期，由 Runtime 与领域服务裁决 |

单轮协议：

1. Runtime 读取 Ward 新输入、`TutorWorkingState`、当前题目和相关近期答疑情境记忆，装配预算与 Policy。
2. 模型输出一个主要教学动作、可选辅助动作、受控工具请求、回复、会话指令与工作状态候选 patch。
3. Tool Gateway 只执行白名单工具；结果以受限摘要回填，调用参数与结果摘要进入 Trace。
4. Output Validator 检查反代写、未成年人安全、解释粒度、证据引用、工具权限和预算，可拒绝或降级建议。
5. Runtime 保存已校验的工作状态与会话摘要；Ward 尝试、实际提示、检索与关闭事实由领域服务写入 [事件账本](design-memory.md)，模型判断只作为 Candidate。

每轮有最大工具调用数、模型调用数和 token 预算。连续多轮无有效进展、工具失败或命中安全/反代写边界时，使用 `manage_learning` 细分问题、建议暂停或转交老师；不得无限循环或直接给出可抄写答案。答疑结束后对 `tutoring_episode` 的结算、证据关联与历史召回规则由 [记忆设计](design-memory.md) 定义。

## 六、今日复盘 Agent：事件触发工作流

复盘以当日已锁定的业务事实为基础，先接收 Ward 自评，再呈现支持性对照和可采纳行动。模型负责支持性提问、归纳和建议；领域服务负责指标计算、事实对比、报告版本与异步补充。

```text
锁定当日事实快照
  → 收集 Ward 自评
  → 读取计划、执行、答疑和已到达的行为证据
  → 生成即时复盘与行动建议
  → Ward 采纳 / 暂存 / 结束
  → 异步视觉分析到达时，以新证据生成补充报告版本
```

视觉分析尚未完成时可生成即时复盘，但不得伪装为当时已经知道客观行为结论；新分析到达后创建有证据差异的补充版本。Ward 自评、行动采纳和报告版本变化分别经领域服务写入事实事件。

## 七、AI Runtime、Policy 与 Context

### 7.1 Skill / Policy Registry

Policy 是“AI 如何陪伴 Ward”的程序化知识，不是 Ward Memory。建议目录：

```text
ai_policies/
  planning/negotiation.yaml
  tutoring/socratic_hint_ladder.yaml
  tutoring/anti_cheating.yaml
  reflection/growth_coaching.yaml
  safety/minor_privacy.yaml
```

每个 Skill 包含适用条件、禁止行为、可用工具、输出 Schema、提示模板和版本号。发布后登记 `ai_policy_versions`（`policy_id`、`version`、`content_hash`、`effective_at`、`status`）。运行中 Agent 不可修改 Skill；修改候选必须经过离线评估、人工审核、灰度和可回滚发布。

### 7.2 ContextEnvelope 与 ContextSpec

`ContextEnvelope` 是每次模型调用生成的内部最小证据快照，不是完整 Ward 档案。运行时将固定 Policy、动态事实、对话历史和工具定义投影到调用的相应位置。

```python
class ContextEnvelope(BaseModel):
    version: str
    run: dict                   # run_id、模型、token/工具预算、trace_id
    actor: dict                 # ward、角色、授权与数据最小化范围
    objective: dict             # Agent、控制状态和本轮子目标
    session: dict               # Redis/Checkpoint 中的工作状态
    evidence: list[LearningEvent]
    signals: list[DerivedSignal]
    memory: list[dict]
    knowledge: list[dict]
    policy: dict
    tools: list[dict]
```

| 字段 | 获取方式 | 例子 |
|---|---|---|
| `run` | Runtime 生成 | 模型版本、token 预算、审计 ID |
| `actor` | JWT、Guardian-Ward 绑定、隐私授权 | 当前 Ward 和允许使用的数据范围 |
| `objective` | API 路由 + Agent 控制模型 | “补齐数学任务时长” |
| `session` | Redis 工作记忆 + PostgreSQL checkpoint | 当前答疑目标、Ward 已尝试的步骤、已给引导 |
| `evidence` | 领域主表投影 + `learning_events` 查询 | 当前任务、实际计时、Ward 自评 |
| `signals` / `memory` | [记忆系统](design-memory.md) 的结构化筛选 | 同类任务基线、未完成答疑情境、有效策略 |
| `knowledge` | Skill 绑定知识库、RAG、可信检索 | 年级知识卡、受控资料摘要 |
| `policy` / `tools` | Agent Definition + Policy + 当前权限 | 反代写限制、排程器、题图解析 |

```python
PLAN_CONTEXT_SPEC = {
    "facts": ["today_tasks", "fixed_events", "recent_duration_samples"],
    "signals": ["estimation_bias", "effective_start_strategy"],
    "memory": ["active_commitments"],
    "skills": ["planning.negotiation"],
    "tools": ["constraint_scheduler"],
}

TUTORING_CONTEXT_SPEC = {
    "facts": ["current_question", "ward_attempts", "current_task"],
    "signals": ["knowledge_gap", "effective_strategy"],
    "memory": ["current_session_summary", "related_tutoring_episodes"],
    "skills": ["tutoring.socratic_hint_ladder", "tutoring.anti_cheating"],
    "tools": ["curriculum_retrieval", "image_question_parser"],
}
```

复盘 Agent 读取当日计划/执行/自评/答疑证据与必要近期基线。上下文装配顺序为：鉴权与范围确定 → 读取 Agent 状态 → 查询当前目标事实 → 召回相关 Signal/Memory/Knowledge → 解析 Policy、工具和输出约束 → 按预算压缩裁剪 → 保存 Context Snapshot 与 Trace → 调用模型/受控工具。

上下文优先级：当前 Ward 输入与当前任务事实 > 当前会话关键状态 > 当日及近期证据 > 已验证长期理解 > 外部知识资料。完整对话和原始工具结果不应无限增长；保留最近关键轮次，压缩旧会话为摘要，但不删除原始事实和审计记录。

## 八、模型输出与写回

所有模型输出必须经 Pydantic JSON Schema 校验，并区分事实观察、待确认假设、建议和候选写入：

```python
class AgentResult(BaseModel):
    ward_message: str
    observations: list[dict]    # 必须引用 evidence_ids
    hypotheses: list[dict]      # 低/中置信度，需 Ward 确认
    questions: list[str]
    proposals: list[dict]
    candidate_events: list[dict]
    next_state: dict

class TutorTurnPlan(BaseModel):
    primary_move: PedagogicalMove
    supporting_moves: list[PedagogicalMove] = []
    tool_requests: list[ToolRequest] = []
    session_directive: Literal["continue", "wait_for_ward", "pause", "close", "escalate"]
    evidence_ids: list[UUID]
    ward_message: str
    state_patch: TutorStatePatch
    candidate_observations: list[dict] = []
```

Runtime 校验教学动作、解释粒度、会话指令、工具权限、预算与状态 patch，并记录工具输入/输出摘要、Policy 版本、模型版本和 Trace ID。模型不得输出可直接抄写的答案草稿、任意可执行代码、数据库命令或未注册工具名。

写回分级：

1. **确定性系统事实**：计时、确认计划、实际提示等由领域服务直接写业务主表和 [事件账本](design-memory.md)；
2. **Ward 明确表达**：自评、偏好、反思归因、采纳行动作为 Ward 陈述事件写入；
3. **AI 候选理解**：可能有效策略、可能兴趣或卡点只写 Candidate，经 [记忆规则](design-memory.md) 晋升；
4. **Policy 修改建议**：只进入评估/运营队列，绝不改写线上 Policy。

## 九、实现落点与演进顺序

```text
app/
  ai_runtime/companion_coordinator.py # 统一入口、规则路由与受控 Handoff
  ai_runtime/intent_router.py          # 低置信度结构化意图分类
  ai_runtime/context_builder.py        # ContextEnvelope / ContextSpec
  ai_runtime/model_gateway.py          # 模型、SSE、重试、成本
  ai_runtime/tool_gateway.py           # 工具白名单、检索与审计
  ai_runtime/policy_registry.py        # Policy 版本解析
  ai_runtime/output_validator.py       # 结构化输出与安全校验
  ai_runtime/trace.py                  # Context Snapshot 与运行 Trace
  ai_agents/planning_workflow.py
  ai_agents/reflection_workflow.py
  ai_agents/tutoring_session_runtime.py # 生命周期、状态持久化与结算
  ai_agents/tutoring_react.py           # 有限步、白名单的单轮 ReAct
```

实施顺序：

1. 建立 Agent Run Trace、最小 ContextBuilder 和确定性优先的 Companion Coordinator；
2. 实现计划协商的 ContextSpec、确定性排程和 Ward 确认写入；
3. 实现答疑会话生命周期、动态工作记忆、有限步 ReAct、提示 Policy 和受控检索；
4. 实现即时复盘、异步行为分析补充版本与受控 Handoff；
5. 与 [记忆系统](design-memory.md) 的 Signal 晋升/衰减和 Policy 评估发布闭环集成。
