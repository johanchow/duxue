# 123 单个事实改由代码放行；被判泄露先重试成提示

日期：2026-10-13

事实源：`docs/technical/domain-tutoring.md` 核心原则方案 A、§4.2；spec 见 `.agent/specs/done/leak-gate-deterministic-fact.md`。

- 问题：判官 v2 靠"告诉它 depth"来放行空格里的单个事实，仍是一次 LLM 判断，结果不稳定（note 121：depth-04 曾 0/5）。被拦后孩子只看到兜底话术。
- 讨论过但没采纳的规则（用户提出）："atomic/recall 一律不算泄露；无 depth 或 reasoning 且有题时一律算泄露；其他优先不算泄露"。问题：第一条把保护交给模型自报的标签（depth-05/06 就是谎报用例）；第二条会让所有 `guide` 回退；第三条在受保护时等于给 chat/clarify/non_work 开口子，并把 fail-closed 变成出错放行。
- 决策：
  - `tutor_loop.fact_gate()`：`act=answer` + 声明单个事实（work 的 atomic/recall 或 non_work 的 atomic_lookup）+ 正文 ≤ 40 字（用户定的阈值，原方案 200）+ 不含数字、算式符号、单独 A–D 选项、对错判断、推理连接词 → 放行，不调文字判官。任一不满足交判官。规则宁可误判多一次判官调用，不可误放。带图时图判官照跑；答案标记检查在闸门之前照跑。
  - 判官 `tutoring.leak-judge@v4` 不再接收 `depth`，只按严格标准审（选项、对错也算答案）。`LeakJudgePort.leaks` 去掉 `depth`。
  - `run_tutor_turn()`（生产与评测共用）：`answer_marker`/`leak_detected` 时带 `LEAK_REPAIR`（"泄露："开头）重试一次，重试结果重新完整检查；`leak_check_failed` 不重试。提示词 `tutoring.turn.system.v9`：见"泄露："改用 `guide`（turn.type=work）给最小提示；单个事实回答 ≤ 40 字。
  - `model_fallback` 只在 `run_tutor_turn` 按最终结果记一次（从 `call_tutor_model`/`vet_candidate` 上移）。观测：`tutor.fact_gate`（passed 或命中规则）、`tutor.leak.retry`、`tutor.turn.result` 带 `tutor.leak_retried`；评测报告 guardrail 加 `leak_retries`。
- 测试：闸门每条规则正反例（depth-adversarial 型的数字、选项、对错、推理不放行）、闸门放行时判官调用 0 次、带图仍判图；重试成功展示提示、答案标记也重试、重试仍泄露只记一次 fallback、判官失败不重试、重试无合法候选保留原因；工作流端到端（听写词直答 + 得数被拦后变提示）。全量 528 passed。
- 未做：离线评测 K=5 对照（需真实模型额度）。重点看 depth-00~06 与 guard：depth-04 应稳定 answer，depth-05/06 应为 hint_like 且 `leak_retries` 是否吸收了原来的回退。
- 坑：40 字阈值下，"词义 + 一句记忆法"容易超长而落到判官。提示词同步写了"不超过 40 字"，评测要看 atomic 回答的长度分布是否被压住。
- 坑：泄露重试会让 `StaticTutorModel` 多消耗一个 raw，依赖 raw 顺序的评测测试（flaky 用例）要补一个 raw。
