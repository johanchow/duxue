# 陪伴入口

事实源：[domain-companion](../../docs/technical/domain-companion.md)。

## 目标

Ward 可见对话是 Companion 的 append-only 账本，统一走 `/companion/turn`。自由文本由模型提议 `planning` / `tutoring` / `reflection` / `unclear`。已有焦点时，跨场景切换须独立核查后才 handoff。

## 状态

- 已落地：消息账本、协议信封、确认卡、历史分页、按需看图、清空可见历史、场景切换核查、三选一澄清、按住说话。
- 流式增量不落库；只有通过检查的最终结果写入一条回复。
- `tutoring_messages` 未并入本账本。
- 2026-11-01 `help_offer` 为[目标协议扩展](../../docs/technical/domain-companion.md#522-关闭的-kind-清单)，未进入当前 v1 allow-list；送达必须遵循回复权和前台回执，求助策略由 Study 拥有。

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

- Ward 拍照提问曾在等回复时同时显示待发缩略图和消息里的原图。发送时在同一次界面更新中把本次照片从输入区移入气泡，发送失败时用该消息保存的附件引用重试。回归测试须覆盖回复尚未返回的时段。

- 2026-11-22 Ward 和 Guardian 共用[回复阶段协议](../../docs/technical/domain-companion.md#对话回复阶段)。导师节点进度可沿用图执行器监听。学生启发的起草和核对边界在 `run_tutor_turn` 内，历史执行快照的节点名称可不同，需在实际调用边界发阶段。流中的 Ward 命令使用工作线程自持的数据库会话，避免依赖鉴权会话的生命周期。

- 场景核查修不了无 focus 的第一次误分。核查不可用时会挡住一次真实切换。
- 清空期间在途回复、历史页和图片结果必须对上本地代次。
- 确认计划会关 Run 并新开 Run，指代仍读同一条对话。
- 本机代理指向无进程的端口时，语音识别会报暂时不可用。

- 2026-11-04 Ward默认安静，只有主动求助/查看历史才展开同一Companion对话；收起不清线程、不取消请求、不触发handoff。Challenge口述预览不写本账本，现有自然语言v2签发动作继续兼容。

- 2026-11-04 答疑内图标已复用Study只读挑战预览，保留对话。自然语言路径回归发现挑战后继续原题会新建Run，已增加服务端受控的原Run恢复引用，只在Sprint交互后恢复同Thread/Ward的paused Tutoring Run；不凭客户端引用恢复。契约归[Companion设计](../../docs/technical/domain-companion.md#答疑中的挑战插曲2026-11-04本轮待验收)。

- 2026-11-04 真机发现初路由能识别挑战但独立scene-switch因原题未结束而拒绝，导致明确挑战请求被当作答疑。scene-switch.system.v2允许保留原题的挑战/提醒插曲，仍拒绝仅估时和解题续答；真实模型红绿验证及可重复CLI见 `duxue-server/scripts/check_reminder_sprint_models.py`。

- 2026-11-21 答疑主图按发布边执行。灰度绑定既有 Run 的 graph_version，回放由执行器记录；改边回归须从真实入口验证可选数据读取和审核访问。设计见[答疑主图的执行与切换](../../docs/technical/domain-tutoring.md#13-答疑主图的执行与切换)。测试环境已验证发布、并发重放与回滚；物理手机接口和安卓模拟器界面证据见[验收清单](../specs/tutoring-json-execution.md)。

- 2026-11-21 Ward 语音输入与答疑朗读已实现，待真实童声和听感验收。原生润色可能吞掉孩子改口；导师、逐字引用及发音目标必须消费原始转写，整理稿仅用于学生气泡。两路 ASR 的计量及正文点读授权见[服务端设计](../../docs/technical/design-server.md#ward-实时转写与正式答复朗读)，播放器打断与指标见[端侧设计](../../docs/technical/design-app.md#3-提问转写与答疑朗读)。

- 2026-11-23 排查 trace `8003fa21614623ceda33dba0ca9e9344`（纯文字科普提问“说说美国的国家体制有什么特殊的地方？”）：`IntentProposal` 新增可选闭集字段 `history_image_ref`（`none | needed`，默认 `needed`）与 `thinking`（`default | off`，默认 `default`），`admin_bundle._intent_hints_contracts` 保持对旧 Admin 发布快照的兼容。仅当无本轮新图且无 `compare_previous_image` 时透传给 `TutoringWorkflow`，避免历史图片在纯文字续聊中重复触发 OSS 拉图与 `tutoring.image-target` 多模态调用。本地测试夹具 `companion.intent.json` 保持未改；已通过 `duxue-server/scripts/upgrade_companion_intent_hints.py` 与 `npm run config:import-upgrade` 写入 `duxue-admin-test` 工作草稿并回读核对（`draft_id=d152ad53-5086-43ca-8e7c-002316801a55`，`revision 10 -> 11 -> 12`，`revision 12` 移除历史 `reflection`/`planning` 冗余说明并补充 3 个紧凑正反示例，Prompt 长度由 `1650` 缩至 `816` 字符，digest `5ad2582b49ce44d7eb86b2e15f008bda163df2a96d13bb7278a9596ee0d5d126`，仅变更 `agents/companion.intent.json`，未发布生产）。

- 成人直接发起操作，Ward 每轮按当前输入决定教学保护；断线恢复最终结果。目标契约见[对话领域](../../docs/technical/domain-conversation.md)与[Agent 设计](../../docs/technical/design-agent.md)。

- 2026-11-28 逐轮保护实施中。真实回复可能由旧答疑出口兜底，即使答疑正确也要单独核对每轮路由 trace 的 teaching_policy。测试草稿版本、评测和 Android 验收见[实施清单](../specs/ward-turn-homework-policy.md)。

- 2026-11-28 双端按账户管理多对话。Ward 客户端只在选中线程内翻页，每次首次发送先取得线程 ID，切换时隔离迟到的 UI 更新。成人问答写回原线程前复核版本，已保存课件用来源回复的稳定 ID 关联。两类保存资产均可在删除来源对话后重开。
- Android 真机验证了 Ward 语音新建两页绘本、指定页修改、撤销重做及冷启动重开。绘本页面块 ID 跨版本稳定，每个新版本保留完整快照。专注提醒按账户查正在进行的挑战及未完成题，作业代写判定先于绘本生成。流程和验收明细见[进行中清单](../specs/conversation-artifact-journeys.md)。

- 2026-11-28 双端发送与断流恢复协议见 [Conversation §4.2](../../docs/technical/domain-conversation.md)。Sprint 偏题提示复用本轮意图模型的 `off_sprint_topic` 和当时的挑战 ID，执行前复查挑战仍活跃。与当轮教学保护各自判定。

- Ward 绘本的来源对话在迁移 46 改为带索引的 UUID，跨域可见性仍由应用查询检查。后续写侧合并与旧流程退场见 [工作台验收清单](../specs/edu-workspace-delivery.md)。

- 2026-11-28，Ward 同轮意图同时提供教学策略、创作意图与可选的 Study 控制提议。下一条消息重新判断；仅发起 Sprint 的明确确认可开启挑战。成人批改及备课的核验门禁检查独立求解结果和交付题目的对应关系，低置信逐题保留人工复核标记。
