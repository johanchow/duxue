# 自我总结直接召回落地

2026-10-23。Ward 今日总结的权威数据留在 Evaluation：`self_reviews` 保存当前状态，`self_review_versions` 保存每次确认的原话，`self_review_aspects` 保存关联原话的六维条目。模型只提出候选，Ward 可编辑或删除，未表达的维度没有条目。修订按 `expected_version` 乐观校验，近期查询只返回当前确认版本。

总结入口先从当天答疑题目、任务预计与实际用时生成开放式问题，再由 Ward 语音或文字表达。答疑按当前任务引用、计划按任务池引用读取有限条目，明确标记为 Ward 自述，不能当作掌握证据或直接排程命令。旧 `feeling` 入口保留兼容，停止新投递 `self_review.submitted`；历史事实保留原有审计/删除规则。`long_term_profiles` 未改。

注意：`source_quote` 必须逐字出现在同一版原话中；不要用语义关键词或正则推断主观内容。旧记录没有可验证的逐字来源时，不自动迁移成六维条目。
