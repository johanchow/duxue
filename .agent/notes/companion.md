# 陪伴入口

事实源：[domain-companion](../../docs/technical/domain-companion.md)。

## 目标

Ward 可见对话是 Companion 的 append-only 账本，统一走 `/companion/turn`。自由文本由模型提议 `planning` / `tutoring` / `reflection` / `unclear`。已有焦点时，跨场景切换须独立核查后才 handoff。

## 状态

- 已落地：消息账本、协议信封、确认卡、历史分页、按需看图、清空可见历史、场景切换核查、三选一澄清、按住说话。
- 流式增量不落库；只有通过检查的最终结果写入一条回复。
- `tutoring_messages` 未并入本账本。

## 决策

- 账本只记 `ward | companion` 的已接受输入和已校验最终回复。prompt、路由、Trace、未校验候选不进对话，也不用于 handoff 或 Memory。
- 业务数字每次从目标 Query 刷新。按钮只执行上一轮已启用、服务端签发的动作，过期 409，客户端刷新后不自动重放。
- `planning`：任务增删改查与排期。`reflection`：对自己经历的总结、回忆，以及基于这些经历谈以后。其余咨询、做题、举例、闲聊归 `tutoring`。听不懂或并列主动作不明才是 `unclear`。「我最近都在问什么」归 tutoring，不查历史原句。
- 已有 focus 且初次提议另一业务场景时才调用 `companion.scene-switch`。否决、非法输出或调用失败都留在原场景。无 focus、同场景续接、安全短路、已验证 UI 动作不做这次核查。
- `unclear` 带三项 `intent_choice`，且只能点当前 Thread 最后一条该回复。
- 无明确意图的图片：无焦点或焦点为 Planning 时进入 Planning；其他焦点下走澄清。
- 图片先停在输入区，随文字、语音或发送带出。只发图时请求正文用「请看这张图片。」，气泡不重复这句。
- 历史图按消息和附件序号按需读取：视口内缩略图，点击后原图全屏。
- 窗口：当前 Thread、排除本轮的最近 8 句、合计 2400 字、最多 8 张已授权图。读不出就告诉模型无法读取。系统自动追加的「先回到任务」尾巴不进窗口。监护人侧 `task_intake` 不读 Ward 窗口。
- 清空用历史代次。同一 `command_id` 重试不推进代次。原始消息、附件、Checkpoint、Trace、任务、会话和长期记忆都不删。
- 气泡：读学 AI 靠左可占满行；孩子靠右、最多三分之二行宽。ASR 先握手再鉴权；按住只出草稿，松手才交终稿。带图的 turn 客户端等待 90 秒。
- 上滑分页只影响展示。本地没有 Thread 时恢复该 Ward 最近有消息的 Thread。Ward 首页唯一 AI 入口是底部 VoiceComposer。

## 注意

- 场景核查修不了无 focus 的第一次误分。核查不可用时会挡住一次真实切换。
- 清空期间在途回复、历史页和图片结果必须对上本地代次。
- 确认计划会关 Run 并新开 Run，指代仍读同一条对话。
- 本机代理指向无进程的端口时，语音识别会报暂时不可用。
