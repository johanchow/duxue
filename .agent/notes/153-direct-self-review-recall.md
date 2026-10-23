# 今日总结直接召回的领域决策

日期：2026-10-23

- 决策：Evaluation 是 Ward 总结原话、确认版本和六维 `ReviewAspect` 的唯一权威来源；近期回顾、相关答疑和 Ward 明确请求的相关计划使用其受权 `GetRecentSelfReviews` Query。按日期、任务/主题和用途裁剪，只返回少量当前确认条目，保留自述标记与原话定位。
- Memory 不因提交或修订总结生成 `daily_review` Episode，也不在 `MemoryBundle` 中复制六维条目。`episodic_memories` 继续用于答疑等有独立事实来源的经历；长期 Signal 若将来需要自述证据，须另定义最小来源引用、独立样本及修订失效规则。
- 现状：`self_review_aspects`、版本化原话、`GetRecentSelfReviews` 均尚未实现。REST/Reflection 当前仍投递只有日期和体感的 `self_review.submitted`；后续接入直接召回时停止新投递，历史账本按既有审计/删除规则处理。答疑目前只读取 MemoryBundle 和当前对话窗口，不会自动读总结。
- 文档同步：更新 Evaluation、Memory、DDD Overview、Companion、Tutoring、Planning 的边界和契约；此前 `.agent/notes/151-retire-focus-kit-and-review-model.md` 中“确认后向 Memory 发自述事实”以及 `.agent/notes/152-memory-confirmed-daily-review.md` 的 `daily_review` 方案均由本决策替代，作为历史讨论记录保留。
- 验证：本轮仅修改设计文档与决策笔记；运行 `git diff --check` 并检查过时 `daily_review` 流程引用，不涉及运行时代码或数据库变更。
