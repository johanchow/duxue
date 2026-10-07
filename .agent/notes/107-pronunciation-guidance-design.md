# 发音辅导采用通用多模态 capability

日期：2026-10-07

正式事实源：`docs/technical/domain-study.md` §4.6 与 `docs/technical/domain-companion.md` §5.2；原 proposal 已收缩为迁移索引。

- 发音辅导属于 Study & Tutoring 的只读教学展示，不新增 Bounded Context、Aggregate、Entity、Domain Service 或 Domain Event，也不写 `VerifiedTurn` / `LearningFactRecorded.v1`。
- 不新增 `PronunciationTargetExtractor` 或 `PronunciationGuideGateway`。图片目标理解与发音讲解复用 Application 拥有的 `ModelGatewayPort`，通过版本化 capability profile 和不同结构化 Schema 区分；Infrastructure Adapter 负责实际多模态/文本模型调用。
- pronunciation 不是新的 Agent Loop，也不是专属固定工作流：Application 在通用能力执行框架中选择一次 `pronunciation-guidance.v1`。模型直接理解本 Turn 的文本、已授权图片和指代，并返回 `lesson`、`clarify`、`no_match` 或 `rejected` 之一；澄清后的新 Turn 重走同一 profile。
- 不建立 `PronunciationRequest` 代码类型或 Domain `PronunciationTarget`。不再设立 `TextSelectionProposal` 或 `ResolvedTextTarget` 这类专属两阶段 DTO；附件 ACL、Schema 和候选可追溯性由通用 Application 校验处理。
- 播放文本来自已校验 lesson 候选；TTS 的 voice、速率、缓存和物理引用属于 App/Server 设计，不进入 Domain 模型。
- Prompt 不按学科整套复制。请求由公共 instruction、capability profile、可选 locale profile、运行时上下文、工具 allow-list 和输出 Schema 组成，合法组合必须登记、版本化和回归评测；发音 profile 的工具集合为空。
- 首期不扩展 Companion `MediaRef.kind=audio`。`pronunciation_lesson` 通过 `object_ref` 读取 View，点击播放后用 `speech_ref + rate` 请求按需 TTS；TTS 失败不改变已完成 Run 或 Study 状态。
