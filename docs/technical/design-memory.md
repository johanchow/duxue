# 读学系统 — 孩子理解与记忆技术设计

> 状态：讨论稿
> 版本：v1.0
> 适用范围：`duxue-server` 的事实账本、三层 Ward 记忆、理解信号与长期画像
> 关联文档：[Agent 技术设计](design-agent.md) · [产品架构](../product/ARCHITECTURE.md) · [孩子理解引擎与记忆系统 PRD](../product/prd-memory.md) · [服务端详细设计](design-server.md)

## 一、目标与边界

本设计为 Ward 陪伴能力提供统一、可追溯、可校正的记忆底座。它服务于计划协商、启发式答疑和今日复盘等 Agent；各 Agent 的入口路由、工作流、工具和模型协议以 [Agent 技术设计](design-agent.md) 为唯一事实源。

系统的目标不是让模型“记住一切”，而是让运行时在正确时机取得最小必要、受权限控制的信息。长期竞争力来自对 Ward 学习过程的持续理解，而非孤立聊天记录或模型标签。

### 1.1 核心原则

- **事实优先**：模型不能将猜测、标签或一次对话中的推断写成事实。
- **最小记忆与最小召回**：仅保留和召回当前目标相关的信息，不将完整 Ward 档案和历史对话注入模型。
- **可校正与可衰减**：对 Ward 的理解是带证据、置信度和有效期的主张，不形成永久标签。
- **业务状态单一事实源**：业务主表是各领域权威状态；事件账本不替代业务表。
- **程序规则与 Ward 数据分离**：教学、安全和工具规则属于版本化 Policy，不是 Ward 记忆，详见 [Agent 技术设计](design-agent.md)。
- **受控删除**：普通删除由外键阻止；注销/被遗忘权依赖显式应用工作流，而非数据库 Cascade。

### 1.2 非目标

- 不以向量检索替代结构化业务查询；任务、时间、权限与计划约束必须由领域服务处理。
- 不允许模型直接写业务表、长期画像或事实账本。
- 不作心理/医疗诊断，不以“懒惰”“注意力差”等道德或病理标签描述 Ward。
- 不以完整聊天记录或模型隐式推理过程作为可长期召回的记忆。

## 二、记忆总体架构

```text
事实底座（不是 Ward Memory）
领域主表（权威业务状态）
  daily_schedules · tasks · tutoring_sessions · self_reviews · behavior_segments
                              │ 同事务 / Transactional Outbox
                              ▼
                 Fact Event Ledger · learning_events
                              │
三层 Ward Memory              ├─ 当前会话投影 → 1. Working Memory
                              ├─ 会话结算/近 5 天摘要 → 2. Episodic Memory
                              └─ 聚合、验证、衰减 → 3. Semantic Memory
                                                        ├─ Derived Signals（证据化理解原子）
                                                        └─ Long-Term Profile（Active 长期 Signal 的投影）
                                                                      │
                                                                Context Builder 按需召回

PostgreSQL · Redis · Celery · OSS
```

`learning_events` 是证据底座，不计为一层 Ward Memory。三层的划分按生命周期与抽象程度：会话级的 Working Memory、近期具体经历的 Episodic Memory、跨会话的 Semantic Memory。`DerivedSignal` 与 `LongTermProfile` 也不是两层独立记忆：前者是第三层的规范化、可追溯来源，后者是其中 `Active + long_term` Signal 的可重算读模型。

数据对象关系如下：

```text
业务事实 Facts
  → 可校正理解 Signals / Claims
  → 可按需召回的 Ward 记忆 Memory
  → 本次模型调用的最小 Context
```

| 类别 | 定位 | 回答的问题 | 是否可由模型直接写入 |
|---|---|---|---|
| 事实 | 证据底座，不是 Memory | 发生了什么？如 19:10 开始任务、Ward 提交自评、实际给出提示 | 否；由业务服务或已验证系统事件写入 |
| Working / Episodic Memory | 第一、二层 Memory | 当前会话与近期具体经历中哪些信息值得召回？ | 由 Runtime、事件和结算管道维护 |
| Derived Signal | 第三层 Semantic Memory 的规范化来源 | 多次事实说明了什么？如估时偏短、画图策略可能有效 | 仅能提出候选；须经规则、Ward 确认或后续证据晋升 |
| Long-Term Profile | 第三层的聚合投影，不是独立 Memory | 哪些已验证长期规律可被业务快速消费？ | 由 Active 长期 Signal 重算，不直接写入 |

## 三、事实层：业务主表与学习事件账本

业务主表继续是权威状态。`learning_events` 是供 AI 上下文、异步理解和审计使用的不可变事实流水；它不替代 Event Sourcing，也不允许模型直接写入。

### 3.1 事件写入时机

| 业务动作 | 领域主表写入 | 同步追加的 Fact Event |
|---|---|---|
| Ward 确认计划 | `DailySchedule` / `Task` | `plan_confirmed`、`task_scheduled` |
| 开始、暂停、完成任务 | 任务/会话状态 | `task_started`、`task_paused`、`task_completed` |
| Ward 提问与尝试 | `TutoringSession` / 消息记录 | `tutoring_question`、`ward_attempt` |
| 实际给出提示或检索资料 | 答疑消息/审计记录 | `hint_given`、`knowledge_retrieved` |
| Ward 提交自评 | `SelfReview` | `self_evaluation_submitted` |
| 视觉流水线完成分析 | `BehaviorSegment` | `behavior_segment_generated` |
| Ward 采纳行动 | ActionableTip / 计划更新 | `strategy_adopted`、`action_tip_adopted` |

领域状态与事件必须同事务写入，或通过 Transactional Outbox 保证一致：业务状态成功而事件丢失、或事件存在但业务状态回滚，均不可接受。来源四元组 `source_type + source_id + event_type + source_version` 是幂等键。

```python
class LearningEvent(BaseModel):
    id: UUID
    ward_id: UUID
    event_type: str
    occurred_at: datetime
    scope: dict                 # day / plan / task / tutoring_session
    source: Literal["ward", "guardian", "system", "cam"]
    confidence: float | None    # 非确定性系统分析必须填写
    payload: dict               # event_type 对应的、可版本化内容
    evidence_refs: list[str]   # 业务记录/对象存储的受控引用
    visibility: str             # ward / guardian / system
    retention_policy: str
```

`source` 表示事实的业务主体/写入侧，不表示模型身份：

| 值 | 含义 | 示例 |
|---|---|---|
| `ward` | Ward 发起或确认的动作 | 确认计划、开停任务、提问、自评、采纳行动 |
| `guardian` | 监护人发起的动作 | 传递任务确认、留言 |
| `system` | 领域服务、定时任务或服务端分析流水线落账 | 行为片段归并、日终衰减、会话结算 |
| `cam` | 读学Eye 设备上报 | 帧元数据、设备心跳相关事实 |

摄像端上报使用 `cam`；服务端 VLM/归并产出的 `behavior_segment_generated` 使用 `system`，可带 `confidence`。稳定核心字段保证审计、权限与时间线可靠；`event_type + payload` 保持扩展性。

## 四、第三层语义记忆：带证据的 Signal / Claim

第三层语义记忆不是第二份事件日志，而是由事件和业务事实计算得到的理解视图。`DerivedSignal` 是其规范化来源：每条 Signal 都必须可追溯、可失效、可被 Ward 纠正。`scope=task/recent` 的 Signal 是从具体经历走向长期理解的中间状态；只有 `scope=long_term AND status=active` 的 Signal 才投影到 `long_term_profiles`。

```python
class DerivedSignal(BaseModel):
    id: UUID
    ward_id: UUID
    signal_type: str
    subject: str | None
    scope: str                  # task / recent / long_term
    value: dict
    statement: str              # 面向运行时的简洁、中性解释
    confidence: float
    observed_from: datetime
    expires_at: datetime | None
    status: Literal["candidate", "active", "challenged", "expired"]
    policy_version: str
```

例如，不记录“Ward 数学差”，而记录“近 14 天的 4 次通分任务中，有 3 次在寻找最小公倍数时主动求助；画倍数表后有 2 次继续完成。该策略有效性为候选，14 天后复核”。证据通过 `derived_signal_events` 关联多个 `learning_events` 保存，不能以竞争性的 JSON 证据副本替代。

### 4.1 产生、晋升和使用时机

- **即时计算**：运行时读取近期同类任务事实，用于时长基线、当前目标和可用时间等确定性业务判断。
- **会话结算**：任务完成、答疑结束、自评提交后，Celery 从事件提炼情境记忆和 Candidate Signal。
- **定时演进**：每日任务重新计算基线、衰减旧主张，并检查兴趣或有效策略是否满足晋升条件。
- **运行时消费**：只召回与当前目标直接相关的 Active Signal；Candidate Signal 只能用于温和追问，不能作为确定结论呈现。

状态机：

```text
Candidate --满足规则或 Ward 明确确认--> Active
Candidate --达到有效期且证据不足--> Expired
Active --出现反证或 Ward 否认--> Challenged
Challenged --重新满足规则--> Active
Active / Challenged --长期无支持或留存到期--> Expired
```

### 4.2 Signal Taxonomy 与 `value` Schema（v1）

`signal_type` 是受控、版本化枚举。模型只能从中选择类型并提出 Candidate，不能发明画像维度；成立度由领域服务按独立会话数、证据可靠性、时间衰减、Ward 明确确认和反证计算。具体阈值由版本化 Policy 管理，不写死在 Prompt。

| `signal_type` | `scope` | `value` 必填字段 | 主要事实来源 | 晋升为长期理解的条件 |
|---|---|---|---|---|
| `focus_endurance_baseline` | `long_term` | `baseline_minutes`、`sample_count`、`window_days`、`calculation_method` | 有效学习会话、行为片段 | 达到最小有效会话样本；每次聚合均可重算和覆盖 |
| `estimation_bias` | `recent` / `long_term` | `direction`、`median_delta_minutes`、`sample_count`、`window_days` | 计划预估、实际完成时长 | 多个独立任务持续呈现同方向偏差 |
| `knowledge_gap` | `task` / `recent` / `long_term` | `subject`、`skill_key`、`support_session_count`、`resolved_session_count` | Ward 求助、提示、任务结果 | 同一具体知识步骤跨多个独立任务重复出现；不得表述为学科能力标签 |
| `effective_strategy` | `recent` / `long_term` | `strategy_key`、`applied_count`、`positive_outcome_count`、`comparison_window` | 行动采纳、后续任务结果、Ward 反馈 | 有重复采纳及正向结果，或 Ward 明确确认有效 |
| `stable_interest` | `recent` / `long_term` | `topic_key`、`independent_session_count`、`active_expression_count`、`last_observed_at` | 主动提问、保存探索、完成探索任务 | 跨多个独立会话且包含 Ward 主动行为；单次提及只能是 Candidate |
| `planning_preference` | `recent` / `long_term` | `preference_key`、`selection_count`、`completion_rate`、`window_days` | Ward 确认计划、任务排序、实际完成 | Ward 多次自主选择并在不同日期保持稳定 |
| `reflection_accuracy_trend` | `recent` / `long_term` | `metric`、`direction`、`sample_count`、`window_days` | Ward 自评、锁闭后生成的客观聚合 | 由代码计算多个复盘的偏差趋势；不表述为诚实或品格问题 |

`statement` 只能依据 `value` 和关联证据生成，采用中性、可行动且不贴标签的语言。`long_term_profiles` 是 `scope=long_term AND status=active` 的聚合读模型，按维度完整重算并覆盖旧快照；它不追加事件，也不直接保存证据。

## 五、三层 Ward Memory、表映射与生命周期

| 层级 | 记忆类型 | 表 / 存储 | 创建与更新时机 | 主要内容 | 结束与清理 |
|---|---|---|---|---|---|
| 第一层 | 工作记忆 | Redis；必要时客户端 SQLite 暂存 | `StudySession` 开始/恢复、答疑消息、未确认计划草稿；每轮更新 | 当前任务、当前目标、最近关键对话、已给引导、未确认草稿 | 完成、放弃或超时后显式关闭；TTL 仅兜底 |
| 第二层 | 情境记忆 | PostgreSQL `episodic_memories` + `episodic_memory_events` | 答疑关闭、任务完成、学习会话结算、自评提交和日终补偿；由 Outbox Worker 异步生成 | 近 5 天任务、卡点、自评、行动承诺、兴趣信号及答疑过程摘要 | 近 5 天热窗口后归档；关联事实仍按留存策略保存 |
| 第三层 | 语义/长期记忆 | `derived_signals` + `derived_signal_events`；`long_term_profiles` 仅为投影 | 会话结算产生 Candidate；每日聚合更新状态/置信度/有效期；Active 长期 Signal 变化后重算 Profile | 经验证或待验证的策略、具体知识卡点、成熟兴趣、估时基线 | Signal 被挑战、到期或衰减为 Expired；Profile 整体覆盖重算 |

`episodic_memories` 与 `derived_signals` 都是派生读模型。`long_term_profiles` 不是另一份可写语义数据，而是第三层 Active 长期 Signal 的物化投影。它们的消费者可重复执行，幂等键分别为 `memory_type + aggregate_id + aggregate_version` 与 `ward_id + signal_type + scope + dimension_key`；若物理表需要新增可索引聚合标识或唯一约束，以 [design-server.md](design-server.md) 为唯一物理 Schema 来源。

`StudySession` 记录一次 Task 的执行总体状态；`study_session_intervals` 记录暂停/恢复区间，并保证每个 Session 最多一个未关闭 Interval。长时间暂停跨日时，日终任务以 `auto_settled` 或 `abandoned` 关闭会话；后续重新开始创建新 Session。

### 5.1 工作记忆的增量更新与压缩

工作记忆不是对当前会话原始记录的单一“总结”。它是当前领域 Run 的可校正运行状态，由确定性业务状态、已验证的交互/工具事实，以及为控制上下文预算而保留的少量会话摘要共同组成。例如答疑工作记忆中的当前题目来自任务或题图解析；Ward 已明确表达的尝试、实际给出的提示和已检索资料来自领域记录或已校验工具结果；只有较早的对话连续性可压缩为 `dialogue_summary`。

工作记忆在状态变化点增量更新，而非定时批量总结：

| 触发 | 更新内容 |
|---|---|
| `StudySession` 开始或恢复 | 初始化/恢复当前任务、会话状态和当前目标 |
| Ward 输入 | 追加可观察的尝试、问题或目标；必要时修正临时卡点假设 |
| 实际提示或受控工具结果 | 更新已给支持、当前策略和受限结果摘要 |
| 未确认计划草稿变化 | 更新草稿、约束和待澄清项 |
| 暂停、关闭或超时 | 显式关闭工作记忆，并触发后续情境记忆结算 |

运行时以“旧工作状态 + 新输入 + 已验证事实/工具结果 + 经校验的状态 patch”归约出新状态。模型可提出 `state_patch` 或摘要候选，但 Runtime/领域规则必须校验 Schema、来源、权限和 Policy 后才可写入；模型不得凭推测写入事实、稳定能力标签或长期理解。关键状态同步写入可恢复的 PostgreSQL Checkpoint，Redis 仅作为低延迟副本。

`dialogue_summary` 采用滑动窗口压缩：近期关键原文/结构化事件保持可见，只有在超过条数或 token 预算时才将更早内容压缩为中性、可追溯的摘要。摘要只保留当前目标所需的 Ward 尝试、已给支持、已验证理解、暂定卡点和下一步；不得替代原始消息或事实事件。窗口大小、token 阈值和压缩频率是版本化 Runtime 配置，不能由模型自行决定。

### 5.2 答疑情境记忆：复用 `episodic_memories`

`TutoringEpisodeMemory` 是答疑的逻辑 Memory 类型，不是新表：使用 `episodic_memories` 中 `event_type = "tutoring_episode"` 的记录存储，并通过 `episodic_memory_events` 关联该次答疑的多个 `learning_events`。原始对话由 `tutoring_messages` 保存；情境记忆只保存可用于日后连续引导的最小、结构化摘要。

```python
class TutoringEpisodePayload(BaseModel):
    schema_version: Literal["tutoring_episode.v1"]
    tutoring_session_id: UUID
    task_id: UUID | None
    subject: str | None
    skill_keys: list[str]              # 受控知识点标识
    problem_ref: str | None            # 受控题目/图片引用，不复制原件
    ward_attempts: list[dict]          # Ward 实际表达或提交的步骤
    reasoning_trajectory: list[dict]   # 尝试 → 修正 → 验证；不猜测内心过程
    support_given: list[dict]          # 教学动作、解释粒度、资料引用
    outcome: Literal["resolved", "partial", "unresolved", "paused"]
    ward_self_explanation: str | None
    next_step: str | None
```

Payload 存在 `episodic_memories.raw_cues`，`summary` 只保留面向 Context Builder 的简洁回顾，`ward_id`、`event_date`、`decay_weight` 使用稳定字段。`reasoning_trajectory` 仅陈述 Ward 可观察到的表达和修正，例如“先尝试相加，画关系图后能说明变量关系”；禁止归纳为“数学差”“逻辑能力弱”等能力或人格标签。

答疑进行中，Runtime 仅更新 Redis/Checkpoint 工作记忆。每个 Ward 输入、实际提示和工具事实写入事件；会话关闭、暂停或超时后，Outbox Worker 将有关事件结算为一条 `tutoring_episode` 并关联全部证据。幂等键应为 `tutoring_episode + tutoring_session_id + session_version`。

### 5.3 召回与上下文消费

运行时优先以结构化条件筛选，而非语义搜索：当前任务/题目与 Ward 输入 → 当前会话工作记忆 → 近 5 天同一 `skill_key` 的未解决或部分解决 `tutoring_episode` → 已验证的 `effective_strategy` 或 `knowledge_gap` Signal → 受控资料。只投影当前目标相关字段，不能把完整原始对话、完整画像或原始工具结果无限注入 Prompt。

可选 `pgvector` 仅用于对近期文本、资料或学习产物的语义召回；不能替代结构化时间、任务、权限和事实查询。ContextEnvelope、各 Agent 的 ContextSpec、token 裁剪与模型调用协议详见 [Agent 技术设计](design-agent.md)。

### 5.4 内部 Memory API

Memory API 是同一服务进程内的领域接口，不是面向 App 的公开 REST API。Agent/ContextBuilder 不得直接查询 `learning_events`、`episodic_memories`、`derived_signals` 或 `long_term_profiles`；它们通过 `MemoryFacade` 获取经授权、裁剪且带证据引用的 Memory Bundle。

```python
class MemoryContextRequest(BaseModel):
    ward_id: UUID
    actor_id: UUID
    actor_role: Literal["ward", "guardian", "system"]
    use_case: Literal["planning", "tutoring", "reflection"]
    task_id: UUID | None = None
    study_session_id: UUID | None = None
    tutoring_session_id: UUID | None = None
    skill_keys: list[str] = []
    memory_types: set[Literal["working", "episodic", "signal", "profile"]]
    visibility_scope: set[Literal["ward", "guardian", "system"]]
    item_budget: int
    token_budget: int

class MemoryBundle(BaseModel):
    working_state: dict | None
    episodic_memories: list[dict]
    active_signals: list[dict]
    profile_projection: dict | None
    evidence_refs: list[dict]
    retrieval_version: str
    truncated: bool

class MemoryFacade(Protocol):
    def resolve_context(self, request: MemoryContextRequest) -> MemoryBundle: ...
    def get_working_state(self, ward_id: UUID, study_session_id: UUID) -> dict | None: ...
    def get_recent_episodes(self, ward_id: UUID, skill_keys: list[str], *, outcome: str | None, limit: int) -> list[dict]: ...
    def get_active_signals(self, ward_id: UUID, signal_types: list[str], *, scope: str) -> list[dict]: ...
    def get_profile_projection(self, ward_id: UUID, dimensions: list[str]) -> dict: ...
```

`resolve_context` 是 Agent 的唯一聚合读入口；其他 `get_*` 仅供经过鉴权的领域服务或确定性业务逻辑使用。Facade 必须执行 Ward/角色/`visibility` 授权、结构化优先筛选、条数与 token 预算、脱敏、证据投影和 Trace 关联；不能返回完整原始对话或未经验证的长期结论。

写接口与读接口严格分离，模型无权调用：

| 签名 | 调用者 | 作用 |
|---|---|---|
| `record_learning_event(...) -> LearningEvent` | 领域服务 | 同事务写确定性事实与 Outbox |
| `settle_episodic(event_ids, aggregate_ref) -> EpisodicMemory` | Outbox Worker | 结算情境记忆并关联证据 |
| `propose_candidate_signal(event_ids, proposal) -> DerivedSignal` | Worker / 受控 Runtime | 创建带证据的 Candidate |
| `evolve_signals(ward_id, at) -> None` | 每日 Worker | 晋升、挑战、衰减和到期 |
| `rebuild_profile(ward_id) -> LongTermProfile` | Profile Worker | 从 Active 长期 Signal 完整重算画像 |
| `challenge_signal(signal_id, ward_statement) -> DerivedSignal` | Ward 纠正领域服务 | 写入反证/确认并改变 Signal 状态 |

未来若需要拆分服务，可原样将这些 Pydantic Request/Response 契约暴露为内部 HTTP/gRPC API；在当前 FastAPI 单体中保持 Python 服务接口，避免为读取 Memory 引入不必要的网络边界。

## 六、异步更新、衰减与数据删除

```text
领域服务提交业务状态 + LearningEvent + Outbox
  → Outbox Consumer / Celery
      ├─ 创建或更新 Episodic Memory，并关联事实证据
      ├─ 提取 Candidate Signal
      └─ Active 长期 Signal 变化时排队重算 Long-Term Profile

每日 Worker
  → 重算基线、检查晋升门槛、衰减旧 Signal、使到期主张失效
```

Outbox 消费者必须可重试、幂等并可从事件账本重放。模型可辅助生成情境摘要或 Candidate，但 Schema、证据引用、Signal 类型、状态转换、置信度计算和长期画像写入均由 Worker/领域规则校验。

普通删除受 `RESTRICT/NO ACTION` 外键阻止。注销或被遗忘权由受控应用工作流按依赖顺序执行：停止运行会话与 Worker → 清理 Redis 工作记忆和对象存储 → 删除可删除的派生读模型/关系记录 → 按数据政策处理事件与业务事实；不得依赖数据库 Cascade。

## 七、实现落点与演进顺序

```text
app/
  domain/learning_events.py       # 事件账本、Outbox、领域投影
  memory/facade.py                # Agent 的聚合读入口与访问控制
  memory/query_service.py         # 工作/情境/Signal/Profile 专用查询
  memory/episodic_extractor.py    # 情境记忆结算与证据关联
  memory/signal_extractor.py      # Candidate Signal 提取
  memory/signal_promotion.py      # 晋升、反证和状态转换
  memory/decay.py                 # 每日衰减、到期和基线重算
  memory/profile_projection.py    # LongTermProfile 完整覆盖投影
```

实施顺序：

1. 建立 `learning_events`、Outbox 与可重试消费者；
2. 建立工作记忆和 `episodic_memories` 的会话/任务结算；
3. 建立 Signal Candidate、证据关联、晋升/衰减和 Profile 重算；
4. 为答疑引入 `tutoring_episode` 及按知识点和未解决状态的最小化召回；
5. 完成注销/被遗忘权的派生数据清理与留存策略验证。
