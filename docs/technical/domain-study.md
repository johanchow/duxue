# 读学系统 — Study & Tutoring Domain Design

> 状态：讨论稿 · 版本：v2.1  
> 范围：学习执行会话、启发式答疑、任务优先提醒、过程事实，以及一次 Ward 输入内的 `TutoringTurnLoop`。  
> 关联：[系统 Context Map](ddd-overview.md) · [Companion 编排](domain-companion.md) · [Memory Context](domain-memory.md) · [Server 物理设计](design-server.md) · [陪伴 PRD](../product/prd-companion.md)

Context Map 与分层图只在 [ddd-overview.md](ddd-overview.md) 维护。Thread/Run、Harness 驱动、`WorkflowInteractionView` 和 SSE 只在 [domain-companion.md](domain-companion.md) 维护。Episode、Signal 与 Profile 只在 [domain-memory.md](domain-memory.md) 维护。物理表、留存和删除只在 [design-server.md](design-server.md) 维护。

## 一、边界与语言

本 Context 拥有 `StudySession`、`TutoringSession`、已验证的 Ward 尝试、实际提示、理解确认、好奇心观察和会话关闭事实。它不拥有 Thread/Run、长期画像、稳定 Signal，也不拥有实时摄像行为结论。

核心不变量：

- L1–L3 不输出最终作业答案、完整解题或代写。L4 只有 `HintingPolicy` 放行后才允许完整思路，并且必须附带验证问题。
- 单次卡点、单次好奇心不升级为稳定能力或稳定兴趣结论。
- 模型可以起草给 Ward 看的散文；提示等级、按钮、媒体引用、事实写入和“已经记下”只能来自已提交的领域结果。

| 术语 | 本 Context 中的含义 | 明确不是 |
|---|---|---|
| `StudySession` | 一次学习执行。可以不绑定已确认任务 | Thread、计划草稿、摄像片段 |
| `TutoringSession` | 隶属某个未结束 `StudySession` 的答疑会话 | Companion Run 的复制 |
| `VerifiedTurn` | 已通过校验并写入的尝试、提示、理解确认或好奇心观察 | 原始对话、模型候选、Trace |
| `HintLevel` | 当前题目允许的提示等级 L1–L4 | 模型自行选择的下一句话类型 |
| `TutorWorkingState` | 答疑 Run 的 checkpoint | Aggregate、长期记忆、完整 transcript |
| `TutoringTurnLoop` | 一次 Ward 输入内的有界循环 | 跨回合的教学状态机，也不是第二个 Agent |

非目标：不发明交互 `kind`；本期不做作文共创画布、视频媒体、实时监工和拍照搜题。无任务问答与任务进行中的题外提问见下文「无任务答疑」。

### 1.1 控制模型

答疑是混合模式。跨回合的开始、暂停、完成、关闭、取消和超时由应用用例与 Aggregate 状态机控制。`TutoringTurnLoop` 只处理一次 Ward 输入内部的不确定性：理解意图、解析题目或资料、按当前允许等级起草一个交互。

| 决策 | 选择 | 原因 | 拒绝的方案 | 验证 |
|---|---|---|---|---|
| 是否需要循环 | 一次输入内需要 | 本轮可能先检索或看附件，再起草一个合法提示 | 整段答疑一次模型调用；模型连续对孩子自问自答 | 无工具输入直接 `finish_loop`；有附件时先 observation 再起草 |
| 谁控制等级 | `HintingPolicy` | 首轮等级和 L4 门槛是固定教学政策 | 模型自选 `ask_socratic_question` 等动作 | 门槛前的 L4 候选被拒绝 |
| 谁确认循环完成 | `HintingPolicy` 与 `ApplyTutorTurn` | 模型返回的 `finish_loop` 只是候选 | 模型声明“孩子已经懂了”即成功 | 决策拒绝时不写 Fact |
| 循环由谁驱动 | `CompanionCoordinator` | 它是 Process Manager，只编排预算、取消和超时 | 再设一个 Harness 类型 | 未实现的工具由 `ToolGateway` 返回失败 |

`budget_exhausted`、取消和超时由 `CompanionCoordinator` 在模型还能返回 `finish_loop` 之前终止。它们表示本轮没有得到可靠教学结果。

## 二、领域模型

```mermaid
flowchart LR
    SS[StudySession]
    IV[StudyInterval]
    TS[TutoringSession]
    VT[VerifiedTurn]
    SS -->|ID| TS
    SS -->|owns| IV
    TS -->|owns| VT
```

两个 Aggregate 只通过 ID 关联。`TutorWorkingState` 不在这张图里，它是 Infrastructure checkpoint。

### 2.1 `StudySession`

| 项目 | 设计 |
|---|---|
| Identity | `study_session_id`，归属 `ward_id` |
| 子实体 | `StudyInterval` |
| 值对象 | `SessionWindow` |
| 不变量 | 归属当前 Ward；`task_id` 可空；时间区间不重叠；结束后不再计时；无任务会话不能完成任务 |
| 行为 | `start()`、`pause()`、`resume()`、`finish()`、`abandon()` |
| 本地事件 | `StudySessionStarted`、`StudySessionPaused`、`StudySessionResumed`、`StudySessionFinished`、`StudySessionAbandoned` |
| Repository | `StudySessionRepository` |

`finish()` 只接受 Ward 的完成命令。单次执行达到 180 分钟时，调度适配器调用 `PauseStudySession`，会话进入 `paused`，不自动完成。`abandon()` 表示 Ward 退出且不完成；不发布 `StudySessionCompleted.v1`。

```mermaid
stateDiagram-v2
    [*] --> Active: start
    Active --> Paused: pause / 180 分钟上限
    Paused --> Active: resume
    Active --> Completed: finish
    Paused --> Completed: finish
    Active --> Abandoned: abandon
    Paused --> Abandoned: abandon
    Completed --> [*]
    Abandoned --> [*]
```

#### 无任务答疑

学习答疑可以不挂在任何任务上。此时 `StudySession.task_id` 为空，问答照常进行，不修改任何 `Task`，也不能把这次会话完成成某项任务。

只有一种要分开的情况：当前已经有一项任务的 `StudySession` 处于 `active` 或 `paused`，这段时间里孩子又问了与该任务无关的问题。允许简短回答，同时提醒回到那项任务，并且不结束原来的任务会话。

### 2.2 `TutoringSession`

| 项目 | 设计 |
|---|---|
| Identity | `tutoring_session_id`，归属 `ward_id` 与 `study_session_id` |
| 子实体 | `VerifiedTurn` |
| 值对象 | `ProblemRef`、`HintRecord` |
| 不变量 | 所属学习会话未结束；关闭后不能追加；持久化提示不超过 Policy 允许等级 |
| 行为 | `open()`、`apply_validated_turn()`、`record_hint()`、`confirm_understanding()`、`close()` |
| 本地事件 | `TutoringSessionOpened`、`TutorTurnRecorded`、`HintRecorded`、`UnderstandingConfirmed`、`TutoringSessionClosed` |
| Repository | `TutoringSessionRepository` |

```mermaid
stateDiagram-v2
    [*] --> Active: open
    Active --> Active: 尝试 / 提示 / 理解确认 / 好奇心观察
    Active --> Closed: close
    Closed --> [*]
```

`open()` 在进入该学习会话的首次答疑循环时执行，使信封可以引用 `tutoring_session_id`。只展示、尚未产生互动 Fact 的会话保持 `Active`。没有互动 Fact 的关闭不会被 Memory 结算为 Episode。

暂停学习、断线、取消 Run 和预算耗尽都不进入 `Closed`。

### 2.3 实体清单

| 对象 | 类型 | Identity | 参与决策的状态 | 行为 | 不变量 |
|---|---|---|---|---|---|
| `StudySession` | Aggregate Root | `study_session_id` | `ward_id`、`task_id?`、`status`、`version` | `start`、`pause`、`resume`、`finish`、`abandon` | 结束后不计时；无任务不可完成 |
| `StudyInterval` | Entity | `interval_id` | `started_at`、`ended_at?`、`end_reason?` | 由 Root 开关 | 同时只有一个未关闭区间 |
| `TutoringSession` | Aggregate Root | `tutoring_session_id` | `study_session_id`、`status`、`version` | `open`、`apply_validated_turn`、`record_hint`、`confirm_understanding`、`close` | 关闭后不可追加 |
| `VerifiedTurn` | Entity | `turn_id` | `kind`、`hint_level?`、`command_id` | 由 Root 追加 | 只记录已校验事实，不含思维链和工具原文 |
| `ProblemRef` | Value Object | 无 | 授权题目引用与版本 | `validate()` | 引用必须来自授权解析结果 |
| `HintRecord` | Value Object | 无 | `level`、`policy_version` | `within(allowed)` | 等级只可取自 Policy 结果 |
| `HintingDecision` | Value Object | 无 | `allowed_level`、`return_to_task`、`l4_walkthrough_allowed` | `validate()` | L4 未放行时 `l4_walkthrough_allowed=false` |

`VerifiedTurn.kind` 只取 `attempt`、`hint`、`understanding`、`curiosity`。它不是 Companion journal，不保存完整聊天。

```mermaid
classDiagram
    class StudySession {
        +study_session_id
        +ward_id
        +task_id
        +status
        +start()
        +pause()
        +finish()
        +abandon()
    }
    class StudyInterval {
        +interval_id
        +started_at
        +ended_at
    }
    class TutoringSession {
        +tutoring_session_id
        +study_session_id
        +status
        +open()
        +record_hint()
        +close()
    }
    class VerifiedTurn {
        +turn_id
        +kind
        +hint_level
    }
    StudySession "1" *-- "1..*" StudyInterval
    TutoringSession "1" *-- "0..*" VerifiedTurn
```

这张图只含两个聚合内部的根和子实体。`HintingPolicy` 是领域服务，不属于其中任何一个聚合，见 2.4。

### 2.4 `HintingPolicy`

`HintingPolicy` 是无状态领域服务。它根据当前 `HintLevel`、同一题目的已验证尝试次数、Policy 版本，以及本轮是否为任务外提问，返回 `HintingDecision`。它不调用模型，不写 Repository，也不解释开放文本。

规则：

- 新题目从 L1 开始。Ward 继续求提示或再次未通过时，才可升到下一等级。
- L1–L3 禁止最终答案、完整解题和代写。
- 同一题目已有三次已验证的未通过尝试，或 Ward 在 L3 之后明确要求再讲解时，才允许 L4。L4 正文必须包含验证问题。
- 当前 `StudySession.task_id` 非空且会话为 `active` 或 `paused`，或者当前时间落在该任务已确认时段内，而本轮是好奇心或闲聊时，`return_to_task=true`。任务会话保持原状态。
- 无任务会话的好奇心不触发回任务提醒。

开放文本属于索答、代写、好奇心、闲聊还是危机情绪，由一次结构化分类调用给出标签。`HintingPolicy` 只消费这个标签。分类调用不选择教学动作，也不写会话。

## 三、应用用例

模型调用和工具调用发生在 Use Case 事务之外。完成校验通过后，Use Case 才打开本地短事务。全部写用例校验 Ward、会话版本和 `command_id`；同一 `command_id` 返回原结果，同键不同载荷拒绝。

| 触发 | 入口 | Use Case | 领域动作 | 本地事件 | 后续 | 幂等与失败 |
|---|---|---|---|---|---|---|
| Ward 开始学习 | Companion `RunInvocation` | `StartStudySession` | `start()` | `StudySessionStarted` | `StudySessionView` | `command_id`；无 `task_id` 时不发布完成事件 |
| 首次进入答疑 | Companion `RunInvocation` | `StartTutoringSession` | `open()` | `TutoringSessionOpened` | 可引用的 `tutoring_session_id` | 同一学习会话已有未关闭答疑时恢复，不另开 |
| 暂停或 180 分钟 | Ward 命令或 Scheduler | `PauseStudySession` | `pause()` | `StudySessionPaused` | 关闭当前区间 | 重复暂停无新区间 |
| Ward 继续 | Companion `RunInvocation` | `ResumeStudySession` | `resume()` | `StudySessionResumed` | 打开新区间 | 已结束后拒绝 |
| Ward 完成学习 | `StructuredWardCommand` | `FinishStudySession` | `finish()` | `StudySessionFinished` | 有 `task_id` 时同事务写 `StudySessionCompleted.v1` | 无任务会话拒绝完成 |
| Ward 退出且不完成 | 受权退出命令 | `AbandonStudySession` | `abandon()` | `StudySessionAbandoned` | 不发布完成事件 | 不回滚已提交答疑事实 |
| 已校验的答疑候选 | `HintingPolicy` 允许之后 | `ApplyTutorTurn` | `apply_validated_turn()` 或 `record_hint()` | `TutorTurnRecorded` 或 `HintRecorded` | 同事务写一条互动 Fact | 决策拒绝时不启事务 |
| `tutor_understood` | 上一轮信封中的受权动作 | `ConfirmUnderstanding` | `confirm_understanding()` | `UnderstandingConfirmed` | 互动 Fact | 模型正文里的“你懂了”不能触发 |
| `tutor_close` | 受权关闭动作 | `CloseTutoringSession` | `close()` | `TutoringSessionClosed` | 恰好一条 `tutoring.session_closed` | 重复关闭返回原关闭结果 |

互动 Fact 的 `event_type` 为 `tutoring.attempt_recorded`、`tutoring.hint_given`、`tutoring.understanding_confirmed` 或 `tutoring.curiosity_observed`。它们在当轮事务提交。`tutoring.session_closed` 只由 `CloseTutoringSession` 发布一次。Memory 在同时具备关闭事实和至少一条互动事实时结算 Episode；Study 不结算 Episode，也不提出 Signal。

安全拒绝、未通过校验的候选、Trace 和工具原文不发布 Fact。好奇心事实提交成功后，展示文案才可以说已经记下。`stable_interest` 仍由 Memory 按自己的门槛处理。

危机情绪标签使本轮不再给题目提示。Use Case 记录本地安全结果并请求 Guardian 通知端口；通知是否送达不改变答疑 Aggregate。模型不能声称已经通知家长。

### 3.1 `ApplyTutorTurn` 时序

写入只发生在 `HintingPolicy` 允许、并且本轮含已验证事实时。完整的读取和模型调用见第四节。

```mermaid
sequenceDiagram
    participant C as CompanionCoordinator
    participant P as HintingPolicy
    participant U as ApplyTutorTurn
    participant A as TutoringSession
    participant O as Outbox
    C->>P: 当前等级与尝试次数
    alt 决策拒绝
        P-->>C: HintingDecision
    else 允许且含已验证事实
        C->>U: 类型化命令
        U->>A: apply_validated_turn 或 record_hint
        A-->>U: 本地领域事件
        U->>O: 同一事务写入 LearningFactRecorded.v1
    else 允许但只展示
        P-->>C: HintingDecision，不调用 Use Case
    end
```

| 参与者 | 标准类型 | 职责 |
|---|---|---|
| `CompanionCoordinator` | Process Manager | 编排这一轮；不修改 Study 的聚合 |
| `HintingPolicy` | Domain Service | 返回允许等级和是否提醒回任务 |
| `ApplyTutorTurn` | Use Case | 授权并提交本地短事务 |
| `TutoringSession` | Aggregate Root | 拒绝超等级提示和关闭后的追加 |
| `Outbox` | Infrastructure | 与聚合在同一事务中保存 `LearningFactRecorded.v1` |

## 四、`TutoringTurnLoop`

循环由 `CompanionCoordinator` 这个 Process Manager 编排。它不另成一种类型。它只做四件事：组装本轮只读上下文、通过基础设施网关执行模型或工具调用、在 `finish_loop` 时询问 `HintingPolicy`、在预算用尽或取消或超时时停住。未实现的工具由 `ToolGateway` 返回 `tool_error`。Coordinator 不维护工具名单，也不检查 schema 版本。

`tutoring-turn-loop.v1` 只声明本 Run 消息窗口、循环次数和 token 预算。改这些数字就换一份配置。L4 门槛仍只由 `HintingPolicy` 决定。

外层图只表示 Ward 可见的阶段，不是类型图。答疑循环只是其中一条路，走完仍回到计时中的会话：

```mermaid
flowchart TD
    A[Ward 开始或继续学习] --> B[学习会话正在计时]
    B --> C{Ward 这一步做什么?}
    C -->|提问、要提示或回答| D[一次 TutoringTurnLoop]
    D -->|拿出一张提示卡| B
    D -->|预算用尽或本轮失败| E[告诉 Ward 本轮失败]
    E --> B
    C -->|暂停，或满 180 分钟| F[暂停计时]
    F -->|继续| B
    C -->|完成学习| G[结束学习会话]
    C -->|结束答疑| H[关闭答疑会话]
    C -->|取消| I[停止本轮回复]
```

暂停、失败和取消都不关闭答疑会话。完成学习才结束 `StudySession`。结束答疑才关闭 `TutoringSession`。

一次循环内部只使用标准类型。读取走 Query，模型与工具走 Infrastructure，等级判断走 Domain Service，写入走 Use Case 和 Aggregate Root。消息窗口、checkpoint 摘要和 `MemoryBundle` 是 Query 的返回值，不是图上的对象。

```mermaid
sequenceDiagram
    participant W as Ward
    participant I as CompanionTurn
    participant C as CompanionCoordinator
    participant QS as GetStudySession
    participant QJ as GetCompanionTranscript
    participant QM as ResolveMemoryContext
    participant K as CheckpointStore
    participant G as ModelGateway
    participant T as ToolGateway
    participant P as HintingPolicy
    participant U as ApplyTutorTurn

    W->>I: 本轮输入
    I->>C: RunInvocation
    C->>QS: 读 StudySessionView
    C->>QJ: 读本 Run 的消息窗口
    C->>QM: 读 MemoryBundle
    C->>K: 读 checkpoint 摘要
    Note over C: 装成模型上下文。不含完整聊天、思维链和工具原文
    C->>G: 发送该上下文

    alt 模型返回工具调用
        G-->>C: 工具名与参数
        C->>T: 执行调用
        T-->>C: observation 或 tool_error
        C->>G: 把结果加回本轮上下文
    else 模型返回 finish_loop
        G-->>C: 提示草稿
        C->>P: 当前等级与尝试次数
        alt 允许且含已验证事实
            C->>U: 类型化命令
            Note over U: 写入 TutoringSession 与 Outbox，见 3.1
            C-->>I: WorkflowInteractionView
            I-->>W: 提示卡
        else 允许但只展示
            C-->>I: WorkflowInteractionView
            I-->>W: 提示卡
        else 拒绝且预算未尽
            P-->>C: HintingDecision 拒绝
            C->>G: rejected，可再调用一次
        else 预算用尽、取消或超时
            C-->>I: 失败结果，不写 Fact
            I-->>W: 失败说明
        end
    end
```

| 参与者 | 标准类型 | 职责 |
|---|---|---|
| `Ward` | Actor | 发起本轮输入 |
| `CompanionTurn` | Interface | 接收 Turn，把最终结果返回给 Ward |
| `CompanionCoordinator` | Process Manager | 组装只读上下文，编排模型调用、预算、取消和超时 |
| `GetStudySession` | Query | 返回 `StudySessionView`，不修改聚合 |
| `GetCompanionTranscript` | Query | 返回本 Run 的近期消息窗口，不修改聚合 |
| `ResolveMemoryContext` | Query | 返回最小 `MemoryBundle`，不修改聚合 |
| `CheckpointStore` | Infrastructure | 保存并读出 checkpoint 摘要 |
| `ModelGateway` | Infrastructure | 发送上下文并返回候选 |
| `ToolGateway` | Infrastructure | 执行一次工具调用；没有实现则返回 `tool_error` |
| `HintingPolicy` | Domain Service | 判断提示等级和是否提醒回任务 |
| `ApplyTutorTurn` | Use Case | 唯一可以写入答疑事实的入口 |

模型每次只返回一个候选。`tool_error` 或拒绝会回到 `ModelGateway`；预算用尽、取消或超时时，Coordinator 把失败结果交给 Interface。

| 节点 | AI-driven | 循环 / 等待 | 退出条件 | 允许调用 | 禁止 |
|---|---|---|---|---|---|
| `StartOrResumeStudy` | 否 | 确定性用例 | 会话已开始、已恢复，或类型化拒绝 | `StartStudySession`、`ResumeStudySession` | 从 transcript 推断任务 |
| `WaitForWard` | 否 | Actor 等待 | 新的自然语言、受权动作、暂停、完成、关闭或取消 | 校验上一轮动作绑定 | 把断线当作取消或关闭 |
| `TutoringTurnLoop` | 是 | 有界循环 | 完成校验接受恰好一个 Ward 交互；或预算、取消、超时停住 | `finish_loop`；工具调用失败即返回 | 连续发出多个教学动作；声称孩子已掌握 |
| `RunFailure` | 否 | 终止展示 | Companion `failed` 或 `timed_out` | 读当前会话 | 写 Fact 或关闭答疑 |
| `Paused` / `StudyFinished` / `TutoringClosed` / `Cancelled` | 否 | 终止或可恢复 | 对应用例已提交 | 读已提交结果 | 由模型选择这些迁移 |

### 4.1 模型候选与 `finish_loop`

模型在循环中只能返回工具请求、`TutorWorkingStatePatch` 候选，或 `finish_loop`。`finish_loop` 由模型经 `ModelGateway` 返回，不由 Coordinator 代写。

```python
class FinishLoopCandidate(BaseModel):
    status: Literal["needs_input"]
    display_text: str
    kind: Literal["tutoring_hint", "text", "text_media"]
    media_refs: list[str] = []
    state_patch: dict | None = None
```

`display_text` 可以是 Markdown / LaTeX。`kind`、媒体和动作必须能投影为 [Companion Interaction Protocol](domain-companion.md#52-companion-interaction-protocol) 的 `WorkflowInteractionView`。答疑使用 `tutoring_hint`、`text`、`text_media` 和失败时的 `failure`。图片只接受已授权 `media_ref`。视频和正文中的任意 URL 不成为可播放或可跳转媒体。

`return_to_task=true` 时，投影必须包含回任务动作。该动作的 `command` 须登记在 `companion-interaction.v1` 后才能启用；Study 不私自增加 `kind`。回任务不关闭 `StudySession` 或 `TutoringSession`。

`TutorWorkingState` 按 `tutoring_session_id + state_version` 保存 checkpoint。字段限于：`learning_goal`、`ProblemRef`、已验证尝试、`HintLevel` 与 `HintRecord`、尝试次数、`return_to_task`、预算消耗、最近摘要和安全标记。模型提出的 patch 通过校验后才写入。checkpoint 不保存原始对话、思维链和工具原文。

### 4.2 完成校验

`CompanionCoordinator` 收到 `finish_loop` 后调用 `HintingPolicy`。五项同时成立才结束本轮：

1. 候选恰好有一个面向 Ward 的交互。
2. 正文符合当前 `HintingDecision`；L4 未放行时不含完整思路或最终答案。
3. 预算尚未耗尽，安全标签允许放行，或已改写成规定的降级文案。
4. 若包含事实或状态变更，对应 Use Case 已提交。
5. “已掌握”只来自 `ConfirmUnderstanding`，不来自 `finish_loop` 文案。

任一项失败时，向模型返回 `rejected`，预算仍在则可以再选一次。`budget_exhausted`、取消和超时不作为 `finish_loop` 的 `status`。恢复时读取该会话已有 checkpoint、Ward 授权和当前等待点。

### 4.3 工具

| 工具 | 权限 | 前置 | 观察结果 | 失败 |
|---|---|---|---|---|
| `inspect_problem_attachment` | 当前 Ward 的题目附件 | 引用属于本次输入或已授权 `ProblemRef` | `unique`、`ambiguous`、`no_match`、`unauthorized`、`tool_error` | 可要求重拍；无候选时不发选择题 |
| `retrieve_authorized_learning_material` | 已授权资料 | 查询范围在 Spec 内 | 上列结果，另加 `stale` | 超时后继续无资料教学 |

工具结果是不可信输入，不直接修改 Aggregate。模型点名一个没有实现的工具时，`ToolGateway` 返回 `tool_error`。单工具只允许一次瞬时重试，重试不重复不可逆写入。

默认上限：每轮最多 4 次循环、4 次模型调用、2 次工具调用、每个工具 1 次重试。墙钟上限使用 Companion Run deadline。模型自报的剩余预算无效。

### 4.4 状态归属

| 数据 | 权威 | 可写者 | 模型能否直接改 | 保留 |
|---|---|---|---|---|
| 学习/答疑事实 | Study Aggregate | Study Use Case | 否 | 见 design-server |
| checkpoint | `CheckpointStore` | 校验通过后的 `CompanionCoordinator` | 否 | 与 Run 一起删除 |
| 工作上下文 | `ContextBuilder` 的单次装配 | 无持久写 | 否 | 不落业务库 |
| 长期记忆 | Memory | Memory Use Case | 否 | Memory 政策 |
| Trace | Companion Trace | `CompanionCoordinator` | 否 | 脱敏，不含思维链 |

上下文由 `GetStudySession`、`GetCompanionTranscript`、`ResolveMemoryContext` 和 `CheckpointStore` 的返回值装配。其他 Ward 的数据、完整原始聊天和未裁剪工具原文不进入上下文。

### 4.5 结果与恢复

| 结果 | 谁产生 | Ward 看见什么 | 调用方恢复 |
|---|---|---|---|
| `needs_input` | 完成校验通过 | 一张提示、澄清或安全降级 | 等待下一轮输入或受权动作 |
| `rejected` | 完成校验失败 | 不直接展示，回到循环 | 预算内重选动作 |
| `budget_exhausted` / `timed_out` | `CompanionCoordinator` | Companion 失败信封 | 显式重试或重新开始，不延长本次预算 |
| `tool_error` | 工具耗尽且无法降级 | 失败信封 | 有界重试 |
| `conflict` | 会话版本不匹配 | 刷新后的权威会话 | 丢弃本地动作并重读 |
| `cancelled` | `CancelAgentRun` | 当前回复权结束 | 已提交的 Study 事务保留；不发布关闭 Fact |

失败不用空的成功信封表示。成就卡上的时长和攻克数只来自已关闭的 `StudyInterval` 与已提交 Fact；模型只起草鼓励语。

## 五、Query

| Query / View | 消费者与新鲜度 | 来源 |
|---|---|---|
| `GetStudySession` / `StudySessionView` | Ward；用例提交后强一致 | `StudySession` 与区间 |
| `GetTutoringInteraction` / `TutoringInteractionView` | Ward；最近一次已校验 Outcome | `TutoringSession`、已提交 `VerifiedTurn`、已有 checkpoint |

`TutoringInteractionView` 提供当前题目引用、提示等级、是否需要回任务，以及已提交的尝试和提示摘要。业务数字经信封的 `object_ref` 再读一次，不从展示句子解析。Guardian 不通过这两个 Query 读取进行中的答疑正文。

## 六、跨 Context 契约

| 事件 | 生产者 | 消费者 | 幂等 | 失败 |
|---|---|---|---|---|
| `LearningFactRecorded.v1` | `ApplyTutorTurn`、`ConfirmUnderstanding`、`CloseTutoringSession` | Memory `IngestLearningFact` | `source_type + source_id + event_type + source_version` | 投递重试；Study 不因投递失败回滚已提交会话 |
| `StudySessionCompleted.v1` | `FinishStudySession`，且存在 `task_id` | Evaluation；Planning `CompleteTask`（把该 Task 标为 `completed`，见 [Task 状态](domain-planning.md#task-状态)） | `study_session_id + version` | 无任务完成不发布；重复完成返回原结果。Study 不写 `Task` |

信封、SSE 和 Run 生命周期的失败语义以 Companion 为准。Fact 入账与 Episode 结算以 Memory 为准。

## 七、基础设施映射

| Port | Adapter | 超时与失败 |
|---|---|---|
| `StudySessionRepository` / `TutoringSessionRepository` | SQLAlchemy | 用例本地短事务；版本冲突返回 `conflict` |
| `LearningFactPublisher` | Study Outbox | 来源四元组去重；死信与补投见 Memory |
| `AttachmentQuery` / `LearningMaterialQuery` | 授权检索适配器 | 超时、ACL 拒绝映射为工具 observation |
| `SafetyClassifier` | 模型 Gateway 的一次结构化调用 | 超时则本轮不放行题目提示 |
| `GuardianAlertPort` | 通知适配器 | 失败只审计，不改写答疑状态 |

checkpoint、Trace 和 Ward 可见 journal 的存储属于 Companion。Study Repository 不保存完整 transcript。

授权边界是当前 Ward。题目切图、语音转写和展示正文按 design-server 的留存与删除执行。Trace 不记录思维链、完整 Prompt 和工具原文。关联 ID 使用 `run_id + turn_id + attempt + study_session_id`。

## 八、验收场景

```gherkin
Given 新题目的当前等级是 L1
When 模型 finish_loop 要求直接给出最终答案
Then 完成校验返回 rejected 或投影为 L1 降级提示
And 不写答案、Fact 或 Signal

Given 同一题目尚无三次已验证未通过尝试
When 模型候选包含 L4 完整思路
Then HintingPolicy 拒绝该等级
And TutoringSession 不记录该提示

Given L4 已被 Policy 放行
When 候选给出完整思路但没有验证问题
Then 完成校验拒绝该候选

Given finish_loop 的正文写着“你已经懂了”
When 完成校验结束本轮
Then 不调用 ConfirmUnderstanding
And 不写 tutoring.understanding_confirmed

Given 本轮产生一条已验证提示
When ApplyTutorTurn 提交
Then 同事务发布 tutoring.hint_given
And 不发布 tutoring.session_closed

Given Ward 取消当前答疑 Run
When CancelAgentRun 完成
Then 已提交的 Study 事务保留
And TutoringSession 仍不是 Closed

Given StudySession 没有 task_id
When Ward 只进行学习问答
Then 会话可以保持 Active
And 不发布 StudySessionCompleted.v1

Given 进行中的任务会话里出现好奇心提问
When 分类标签为好奇心且事实提交成功
Then 发布 tutoring.curiosity_observed
And 交互包含回任务动作
And StudySession 不被结束
```
