# 已确认今日总结进入 Memory 的边界

日期：2026-10-23

- 领域所有权：六维条目、Ward 原话、确认与修订由 Evaluation 持有；Memory 只接收 `self_review.confirmed` 的版本化最小事实。原话全文和逐句引用留在 Evaluation，Memory 通过受控来源引用定位。
- 记忆分层：一份已确认版本是一条不可变 LearningEvidence；近期 `daily_review` 复用 EpisodicMemory 表，有已确认条目才创建摘要，默认只召回最高确认版本。六维分类不等于六种 Signal 或六列 Memory 字段。
- 修订与乱序：旧 Evidence 留作审计，旧 Episode 退出当前视图；即使新版条目为空也归档旧摘要。旧证据支撑的 Signal 要重评。低版本迟到只入账，不反向覆盖新摘要。
- 画像边界：Ward 的“已懂”“方法有效”“下次想做”是自述，不单凭它们推断能力、策略效果或已执行行动；`affect/context` 默认仅作近期情境，不形成长期人格画像。没有自动锦囊或计划注入。
- 现状差距：当前只写 `self_review.submitted` 的日期/体感到通用 Evidence Ledger，Memory 仅结算 tutoring episode。确认版条目、`daily_review` 结算、版本失效和定向召回仍是设计目标，需在 Evaluation 入口上线后实施。
- 验证：本轮仅修改领域文档和决策笔记，`git diff --check` 用于检查 Markdown 补丁；没有运行代码测试。
