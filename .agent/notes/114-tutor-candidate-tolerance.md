# 114 TutorTurnCandidate 的安全容错

日期：2026-10-10

现象：正常答疑会因 `progress_without_attempt` 或非关键候选字段缺失/额外 provider 字段而被统一回退文案替代。

根因：候选契约把不影响答案保护的教学元数据当作整轮硬失败；`extra="forbid"` 又使 provider 附加调试字段触发结构重试。Grafana 只保留输出摘要，不能用原文直接诊断具体字段。

规避：

- 非 `attempt` 的 `progress` 与 `subgoal_evidence` 只是不推进领域状态，不能导致回退。
- `next_subgoal`、`subgoal_evidence`、`follow_up_question`、`history_ref` 的空白字符串视为未填。只有非空 `next_subgoal` 出现在非 `work_product_help` 时才拒绝整轮。
- `act=pronounce` 漏填 `question_kind` 时按 `chat` 补上。发音卡不看这个字段，不能因此回退。其它 act 仍然必填。提示词要求 note 带 `explanation`，修复时保留必填字段。
- 发音字段摊在 JSON 最外层时，收成嵌套的 `lesson`。提示词给出嵌套示例。不是 `pronounce` 的回复仍然不能带 lesson。
- `same_problem` 缺失时默认 `true`，在已有开放题时 fail-closed；`student_turn_kind`、`is_assignment_content`、`reveals_solution` 使用不放宽保护的默认值。
- 忽略未知候选字段，它们不得进入领域状态或持久化；`act`、`question_kind`、`content` 仍为必填。
- 每次结构校验失败写 `tutor.candidate.rejected` Trace 事件，只记录低基数错误类型、字段与是否重试，不记录孩子或模型文本。
- 对 `clarify + lesson`，lesson 的对象归属尚未确认：丢弃 lesson 并展示澄清问题；仅此安全降级。`answer + lesson` 等其他不一致组合仍按出口检查拒绝。
