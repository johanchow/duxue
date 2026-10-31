# 评估与记忆边界

事实源：[domain-evaluation](../../docs/technical/domain-evaluation.md)、[domain-memory](../../docs/technical/domain-memory.md)。

## 目标

今日总结的原话、确认版本和六维条目只属于 Evaluation。复盘对话只承接孩子对自己经历的回顾，或基于这些经历谈以后。客观报告按证据版本另做。

## 状态

- 已落地：直接召回（`self_reviews` 及版本、六维条目）、确认与修订、按当前确认版本限量查询。默认专注锦囊和 `focus_kits` 已退役。
- 已取消、不要再做：`daily_review` Episode；确认后向 Memory 发自述事实。
- 未做：报告的证据版本化。自述版本不是客观报告版本。

## 决策

- 模型只出候选。Ward 可改可删。没说到的维度没有条目。
- 修订按 `expected_version` 乐观校验。查询只返回当前确认版本，并标明是 Ward 自述。
- `source_quote` 必须逐字出现在同一版原话里。旧记录没有可验证逐字来源时，不自动迁成六维条目。
- 停止新投递 `self_review.submitted`。历史账本按原审计和删除规则保留。旧 `feeling` 入口留兼容。
- Memory 不在 `MemoryBundle` 里复制六维。`episodic_memories` 继续给定答疑等有独立事实来源的经历。
- 「已懂」「方法有效」「下次想做」是自述，不能单独当成能力、策略效果或已执行行动。`affect` / `context` 不形成长期人格画像。
- 没有自动锦囊，也不把总结自动写进计划。计划只在 Ward 明确要求时读取 `next_intent`。
- 复盘等待自评时必须返回有正文的引导。结合本人经历谈以后归 reflection；没有这段经历的一般方法请教归 tutoring。
- 答疑不用总结当掌握证据。主客观对照用 Evaluation 的当前总结，不绕 Memory。

## 注意

- 历史 `self_review.submitted` 仍可能留在证据账本，但不再据此生成总结 Episode 或六维 Signal。
- 通用 Outbox 还没有 `payload_schema_version`。
- Companion 文档若仍写 `RecentSelfReviewsView` 未接入，以 evaluation / memory 的实现章节为准。
