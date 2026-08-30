# 读学系统 — 孩子理解、记忆与 AI 上下文技术设计

> 状态：讨论稿  
> 版本：v1.0  
> 适用范围：`duxue-server` 的计划协商、陪伴答疑、结果复盘及后续深度引导能力  
> 关联文档：[产品架构](../product/ARCHITECTURE.md) · [孩子理解引擎与记忆系统 PRD](../product/prd-memory.md) · [协商式计划 PRD](../product/prd-schedule.md) · [陪伴执行 PRD](../product/prd-companion.md) · [结果评估 PRD](../product/prd-evaluate.md) · [服务端详细设计](design-server.md)

## 一、目标与边界

本设计为长期“Ward 陪伴助手”建立统一智能底座，服务三个 Ward 可感知的 AI 入口：

1. **计划协商 Agent**：通过对话帮助 Ward 澄清任务、时长、可用时间和偏好，形成由 Ward 确认的计划。
2. **今日复盘 Agent**：先接收 Ward 自评，再基于实际执行、答疑和已完成的行为分析，引导 Ward 理解差异并形成下一步行动。
3. **启发式答疑 Agent**：以苏格拉底式提示、可信资料检索和多轮状态维护帮助 Ward 思考，不直接代答或代写。

系统的目标不是让模型“记住一切”，而是让它在正确的时机使用最小必要、可追溯且受权限控制的信息。长期竞争力来自对 Ward 学习过程的持续理解，而非孤立的聊天回答。

### 1.1 核心原则

- **事实优先**：模型不能把猜测、标签或一次对话中的推断写成事实。
- **Ward 主体性**：AI 只能提出建议或草稿；正式计划、反思归因和行动采纳由 Ward 确认。
- **最小上下文**：一次调用仅注入与当前目标相关的信息，不把完整 Ward 档案和历史对话传给模型。
- **可校正与可衰减**：对 Ward 的理解是带证据、置信度和有效期的主张，不形成永久标签。
- **Skill 与 Ward 记忆分离**：专家策略决定 AI“怎样陪伴”；Ward 记忆记录 AI“了解了什么”。
- **业务写入受控**：模型不直接写业务表、长期画像或 Skill；所有写入经领域服务、Schema 校验和必要的 Ward 确认完成。

### 1.2 非目标

- 不将系统实现为可自由互相委托的多 Agent 网络；三个 Agent 共享运行时，但不自由互聊。
- 不以向量检索替代结构化业务查询；任务、时间、权限与计划约束必须由领域服务处理。
- 不允许线上 Agent 自行改写安全、隐私、反代写或专家教学规则。
- 不作心理/医疗诊断，不以“懒惰”“注意力差”等道德或病理标签描述 Ward。

## 二、总体架构

```text
读学 App · Ward
  ├─ 计划协商 Agent        ─┐
  ├─ 今日复盘 Agent        ─┼─→ AI Runtime / Context Builder
  └─ 启发式答疑 Agent      ─┘       │
                                          ├─ Model Gateway / SSE
                                          ├─ Tool Gateway
                                          ├─ Skill & Policy Registry
                                          ├─ Output Validator / Trace
                                          └─ 孩子理解引擎
                                                    │
业务主表 ─→ Fact Event Ledger ─→ 近期记忆 / 理解信号 / 长期画像
                                                    │
                         PostgreSQL · Redis · OSS · Celery
```

三个 Agent 是不同的交互工作流，而非三份独立的 Ward 记忆：

| Agent | 控制模式 | 模型负责 | 领域服务负责 |
|---|---|---|---|
| 计划协商 | 有循环的状态图/工作流 | 理解表达、必要追问、解释草稿 | 任务池、时间约束、确定性排程、确认写入 |
| 今日复盘 | 事件触发工作流 | 支持性提问、归纳、行动建议 | 指标计算、事实对比、报告版本、异步补充 |
| 启发式答疑 | 持久化教学状态机 + 受限工具循环 | 诊断卡点、分级提示、解释 | 安全拦截、知识检索、提示层级、会话记录 |

## 三、四类信息及其关系

```text
业务事实 Facts
  → 可校正理解 Signals / Claims
  → 可按需召回的 Ward 记忆 Memory
  → 本次模型调用的 Context

专家 Skill / Policy 横向约束以上所有过程
```

| 类别 | 回答的问题 | 例子 | 是否可由模型直接写入 |
|---|---|---|---|
| 事实 | 发生了什么？ | 19:10 开始任务、Ward 提交自评、给出 L2 提示 | 否；由业务服务或已验证系统事件写入 |
| 理解信号 | 多次事实说明了什么？ | 近三次数学估时偏短、画图策略可能有效 | 仅能写入候选，须经规则/Ward 确认/后续证据晋升 |
| Ward 记忆 | 哪些过去信息值得日后召回？ | 当前会话摘要、近 5 天卡点、稳定兴趣 | 由事件与信号管道维护 |
| Skill / Policy | AI 应如何做事？ | L1~L4 提示阶梯、反代写、复盘语言边界 | 不可在运行时自动修改 |

## 四、事实层：业务主表与学习事件账本

现有 `daily_plans`、`tasks`、`tutoring_sessions`、`self_evaluations`、`behavior_segments` 等表仍是各自领域的权威业务状态。新增的事件账本不替代它们，而是为 AI 上下文、异步理解和审计提供统一的不可变流水。

### 4.1 事件写入时机

| 业务动作 | 领域主表写入 | 同步追加的 Fact Event |
|---|---|---|
| Ward 确认计划 | `DailyPlan` / `PlanItem` | `plan_confirmed`、`task_scheduled` |
| 开始、暂停、完成任务 | 任务/会话状态 | `task_started`、`task_paused`、`task_completed` |
| Ward 提问与尝试 | `TutoringSession` / 消息记录 | `tutoring_question`、`ward_attempt`、`hint_given` |
| Ward 提交自评 | `SelfEvaluation` | `self_evaluation_submitted` |
| 视觉流水线完成分析 | `BehaviorSegment` | `behavior_segment_generated` |
| Ward 采纳行动 | ActionableTip/计划更新 | `strategy_adopted`、`action_tip_adopted` |

领域状态与事件应通过同一事务或 Transactional Outbox 保证一致：业务状态成功而事件丢失、或事件存在但业务状态回滚，均不可接受。

### 4.2 建议的数据结构

```python
class LearningEvent(BaseModel):
    id: UUID
    ward_id: UUID
    event_type: str
    occurred_at: datetime
    scope: dict                 # day / plan / task / tutoring_session
    source: Literal["ward", "guardian", "system", "cam"]
    confidence: float | None    # 非确定性分析必须填写
    payload: dict               # event_type 对应的、可版本化内容
    evidence_refs: list[str]   # 业务记录/对象存储的受控引用
    visibility: str             # ward / guardian / system
    retention_policy: str
```

`source` 表示事实事件的业务主体/写入侧，不表示模型身份：

| 值 | 含义 | 示例 |
|---|---|---|
| `ward` | Ward 发起或确认的动作 | 确认计划、开停任务、提问、自评、采纳行动 |
| `guardian` | 监护人发起的动作 | 传递任务确认、留言 |
| `system` | 领域服务、定时任务或服务端分析流水线落账 | 行为片段归并、日终衰减、心跳巡检 |
| `cam` | 读学Eye 设备上报 | 帧元数据、设备心跳相关事实 |

注意：摄像端**上报**用 `cam`；服务端 VLM/归并产出的 `behavior_segment_generated` 用 `system`（可配 `confidence`）。模型不直接写事实账本，故不设 `ai`。

稳定核心字段保证审计、权限与时间线可靠；`event_type + payload` 保持可扩展。例如未来可增加 `ward_explained_concept`、`exploration_artifact_created`，无需重构整个上下文系统。

## 五、理解层：带证据的 Signal / Claim

理解层不是第二份事件日志，而是由事件和业务事实计算得到的物化理解视图。每条 Signal 都必须可追溯、可失效、可被 Ward 纠正。

```python
class DerivedSignal(BaseModel):
    id: UUID
    ward_id: UUID
    signal_type: str            # estimation_bias / knowledge_gap / effective_strategy
    subject: str | None
    scope: str                  # task / recent / long_term
    value: dict
    statement: str              # 面向运行时的简洁解释
    confidence: float
    evidence_ids: list[UUID]
    observed_from: datetime
    expires_at: datetime | None
    status: Literal["candidate", "active", "challenged", "expired"]
```

示例：不是“Ward 数学差”，而是“近 14 天的 4 次通分任务中，有 3 次在寻找最小公倍数时主动求助；画倍数表后有 2 次继续完成。该策略有效性为候选，14 天后复核”。

### 5.1 产生与使用时机

- **即时计算**：计划 Agent 打开时，读取近期同类任务事实，计算估时建议和可用时间冲突。
- **会话结算**：任务完成、答疑结束、自评提交后，由 Celery 提炼本次卡点、行动采纳与复盘候选。
- **定时演进**：每日任务重新计算基线、衰减旧主张、检查兴趣或有效策略是否满足晋升条件。
- **运行时消费**：Context Builder 仅取与当前场景直接相关的 Active Signal；Candidate Signal 只可用于温和追问，不能作为确定结论呈现。

## 六、与现有三层记忆模型的映射

`prd-memory.md` 的三层 Ward 记忆继续作为正式设计。本方案补充其来源、写入边界和运行时召回方式：

```text
领域主表
    │
    ├─ Fact Event Ledger（完整、可追溯）
    │      ├─ 当前会话状态 → Working Memory
    │      ├─ 近 5 天筛选/摘要 → Episodic Memory
    │      └─ 聚合、验证、衰减 → Long-Term Profile
    │
    └─ Skill / Policy Registry（独立于 Ward 数据）
```

| 记忆类型 | 对应现有设计 | 存储与生命周期 | 主要内容 |
|---|---|---|---|
| 工作记忆 | `WorkingMemory` | Redis；任务/答疑会话级 TTL，必要时客户端 SQLite 暂存 | 当前任务、当前提示等级、最近对话、未确认草稿 |
| 情境记忆 | `EpisodicMemory` / `episodic_memories` | PostgreSQL；近 5 天为热窗口，原始数据按留存策略归档 | 近期任务、卡点、自评、行动承诺和兴趣信号 |
| 长期 Ward 记忆 | `LongTermProfile` / `long_term_profiles` | PostgreSQL JSONB + 结构化特征；持续衰减与重算 | 经验证的策略、能力趋势、成熟兴趣、估时基线 |
| 程序记忆 | 新增，非 Ward 记忆 | Git 中版本化配置；发布版本登记 PostgreSQL | 专家 Skill、安全策略、Prompt 模板、工具规则 |

可选的 `pgvector` 仅用于对近期文本、资料或学习产物的语义召回；不能替代上述结构化时间、任务、权限和事实查询。

## 七、Skill / Policy Registry

Skill 是“AI 如何陪伴 Ward”的程序化知识，而不是模型对某个 Ward 形成的记忆。

```text
ai_policies/
  planning/negotiation.yaml
  tutoring/socratic_hint_ladder.yaml
  tutoring/anti_cheating.yaml
  reflection/growth_coaching.yaml
  safety/minor_privacy.yaml
```

每个 Skill 至少包含适用条件、禁止行为、可用工具、输出 Schema、提示模板和版本号。发布后登记 `ai_policy_versions`（`policy_id`、`version`、`content_hash`、`effective_at`、`status`）。

运行中的 Agent 不可修改 Skill。它可以基于 Trace 和用户反馈生成“修改候选”，但必须经历离线评估、人工审核、灰度发布和可回滚的版本管理。可自动变化的是 Ward Signal 的数值、置信度和有效期，而不是安全或教学规则本身。

## 八、ContextEnvelope：一次运行的最小证据工作包

`ContextEnvelope` 是 AI Runtime 在**每次模型调用**时生成的内部快照。它不是完整 Ward 档案，也不要求将所有字段原样序列化进 Prompt；运行时会将固定策略、动态证据、对话历史和工具定义投影到模型调用的相应位置。

```python
class ContextEnvelope(BaseModel):
    version: str
    run: dict                   # run_id、模型、token/工具预算、trace_id
    actor: dict                 # ward、角色、授权与数据最小化范围
    objective: dict             # Agent、当前状态和本轮子目标
    session: dict               # Redis/Checkpoint 中的当前工作状态
    evidence: list[LearningEvent]
    signals: list[DerivedSignal]
    memory: list[dict]          # 相关的情境/长期记忆召回
    knowledge: list[dict]       # 教材、专家资料或受控检索结果
    policy: dict                # 已解析的 Skill / 安全规则版本
    tools: list[dict]           # 本次明确授予的工具
```

### 8.1 各字段来源

| 字段 | 获取方式 | 例子 |
|---|---|---|
| `run` | Runtime 生成 | 模型版本、token 预算、审计 ID |
| `actor` | JWT、Guardian-Ward 绑定、隐私授权 | 当前 Ward 和允许使用的数据范围 |
| `objective` | API 路由 + Agent 状态机 | “补齐数学任务时长”，而非泛泛“做计划” |
| `session` | Redis 工作记忆 + PostgreSQL checkpoint | 答疑已到 L2、Ward 已尝试的步骤 |
| `evidence` | 领域主表投影 + `learning_events` 查询 | 当前任务、实际计时、Ward 自评 |
| `signals` | 近期记忆、长期画像及 Signal 查询 | 近三次数学估时偏短 |
| `memory` | 结构化筛选优先，必要时语义召回 | 已采纳但尚未完成的行动承诺 |
| `knowledge` | Skill 绑定知识库、RAG、通过网关的可信检索 | 年级知识卡、来源受控的资料摘要 |
| `policy` | Agent Definition + Skill Registry + 安全策略 | 答疑 L1~L4、反代写限制 |
| `tools` | Agent 状态 × 鉴权 × 工具白名单 | 排程器、教材检索、图片题目解析 |

### 8.2 不同 Agent 的 ContextSpec

Agent 不直接“读取所有 Ward 数据”，而是声明各自的 `ContextSpec`：

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
    "signals": ["topic_stuck_points", "effective_hint_style"],
    "memory": ["current_session_summary"],
    "skills": ["tutoring.socratic_hint_ladder", "tutoring.anti_cheating"],
    "tools": ["curriculum_retrieval", "image_question_parser"],
}
```

复盘 Agent 则读取当日计划/执行/自评/答疑证据与必要的近期基线。若视觉分析尚未完成，先生成即时复盘；分析到达后创建带新证据的补充报告版本，不伪装为当时已知事实。

### 8.3 上下文装配、压缩与可观测性

```text
鉴权与范围确定
  → 读取 Agent 状态
  → 查询当前目标的领域事实
  → 召回相关 Signal / Memory / Knowledge
  → 解析 Skill、工具和输出约束
  → 按 token 预算排序、压缩和裁剪
  → 保存 Context Snapshot 与 Trace
  → 调用模型 / 执行受控工具
```

上下文优先级：当前 Ward 输入与当前任务事实 > 当前会话关键状态 > 当日及近期证据 > 已验证的长期理解 > 外部知识资料。完整对话和原始工具结果不应无限增长：保留最近关键轮次，压缩旧会话为摘要，但不删除事实账本与原始审计记录。

## 九、模型输出与写回规则

模型输出必须经 Pydantic JSON Schema 校验，并区分事实观察、待确认假设、建议和候选写入：

```python
class AgentResult(BaseModel):
    ward_message: str
    observations: list[dict]    # 必须引用 evidence_ids
    hypotheses: list[dict]      # 低/中置信度，需 Ward 确认
    questions: list[str]
    proposals: list[dict]
    candidate_events: list[dict]
    next_state: dict
```

写回分级：

1. **确定性系统事实**（计时、确认计划、已给提示）由领域服务直接写入业务主表和事件账本；
2. **Ward 明确表达**（自评、偏好、反思归因、采纳行动）作为 Ward 陈述事件写入；
3. **AI 候选理解**（可能有效的策略、可能的兴趣）先写 Candidate Signal；仅在后续证据、规则或 Ward 确认满足条件后晋升；
4. **Skill 修改建议**只写入评估/运营队列，绝不改写线上 Skill。

## 十、实现落点与演进顺序

建议在现有 FastAPI + PostgreSQL + Redis + Celery 架构内实现，不预设重型多 Agent 框架：

```text
app/
  domain/learning_events.py       # 事件账本、Outbox、领域投影
  ai_runtime/context_builder.py   # ContextEnvelope / ContextSpec
  ai_runtime/model_gateway.py     # 模型、SSE、重试、成本
  ai_runtime/tool_gateway.py      # 工具白名单、检索与审计
  ai_runtime/policy_registry.py   # Skill/Policy 版本解析
  ai_runtime/output_validator.py  # 结构化输出校验
  ai_runtime/trace.py             # Context Snapshot 与运行 Trace
  ai_agents/planning_workflow.py
  ai_agents/reflection_workflow.py
  ai_agents/tutoring_state_machine.py
  memory/signal_extractor.py
  memory/signal_promotion.py
  memory/decay.py
```

实施顺序：

1. 建立 `learning_events`、Outbox、Agent Run Trace 和最小 `ContextBuilder`；
2. 为计划协商实现 `ContextSpec`、确定性排程和 Ward 确认写入；
3. 接入答疑会话状态机、提示阶梯 Skill、受控知识检索；
4. 接入即时复盘与异步行为分析补充版本；
5. 建立 Signal 晋升/衰减、长期画像与专家 Skill 的评估发布闭环。

该顺序先保证事实和 Ward 控制权，再逐步增加个性化理解，避免长期画像在基础数据不足时过早固化。
