> 已被 [112](112-llm-driven-tutoring-code-guarded-exit.md) 取代：`HintingPolicy` 与 L1–L4 在目标设计中由 `TutorPermitPolicy` 和答案状态机替代。

# 提示策略与教学技能分层

日期：2026-10-07

事实源：`docs/technical/domain-study.md` v2.6 §2.4。

- `HintingPolicy` 仍是等级和 `reply_mode` 的唯一领域服务，不改成可替换提示词。
- 放行后的答法是已登记技能：`problem-hint.v1` 对应 `scaffold`，`direct-gloss.v1` 对应 `direct_answer`。技能不能升等级，也不能把直接作答改成追问。
- 作业题永远阶梯提示。原子释义在没有历史或命中已授权历史时直接作答；有历史时答案要接上那条引用。非法题型按作业题处理。
- 历史候选由 Application 从已提交答疑事实和最近原句窗口取出。模型只能在这组里命中，不能检索全库或编造上次学过。
- 回任务仍由策略决定。技能可以写这句提醒，草稿里没有时由 Application 补上。
- 凡是理解本轮原句的模型调用都带 Companion 的最近 8 句。指代在窗口内对不上时必须追问，不能猜。场景判断、答疑意图、答疑回复、计划审阅和复盘建议已带上这个窗口。
- 直接释义已接到回复路径：好奇心且题型为 atomic 时 `HintingPolicy.reply_mode=direct_answer`，技能 `direct-gloss.v1` 写出词义。作业题、闲聊和安全仍是 `problem-hint.v1`。历史引用必须落在最近原句候选里，否则按 none。题型或历史调用失败分别按 problem 和 none。
