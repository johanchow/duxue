# 122 答疑契约 v4：堵保护口子、拆字段重叠、删无用字段

日期：2026-10-13

事实源：`docs/technical/domain-tutoring.md` v3.3 §4.1–4.2；spec 见 `.agent/specs/done/tutor-turn-contract-hardening.md`。

- 起因：按代码复盘 `tutor-turn.v3`（spec 文件还停在 v2 结构），发现两个保护口子、三组语义重叠的字段、若干没有消费方的字段。
- 保护口子（P0）：
  - `act=clarify` 在 `check_authority` 里直接放行，`content` 和 `candidates` 都不过答案标记和泄露判官。题目受保护时，模型选 clarify 就能把答案写进候选。现在受保护时与 answer/guide 同等检查；判官文本用 `candidate.shown_text`（正文 + 候选）。
  - `relation=new` 会把旧题置 `abandoned`，之后判官的 `problem` 只剩新题摘要，追问旧题答案判不出。没有改 `abandoned` 不受保护的领域语义，只让判官看到本会话最近 3 道题 + 孩子本轮的话（`tutor_loop.judge_problem_summary`，评测共用）。判官提示词 `leak-judge@v3`、`visual-leak-judge@v2`。
- 字段重叠（P1）：
  - `act` 与 `depth` 是同一个决定的两种编码。`_fact_depth` 原来不看 act，`guide + depth=atomic` 会放宽判官。现在只在 `act=answer` 时传 depth；`answer + reasoning` 记 shape flag `answer_on_reasoning`，不拒绝。
  - `progress` 越过 `student_move` 影响计数：`guide + request_hint + progress=submitted` 既不计提示也不计尝试。现在 `WorkTurn` 解析时 `student_move != attempt` 就清空 `progress`、`evidence`。
  - `tutoring.attempt_recorded` 原来只看 `student_move=attempt`，而计数还要求 `evidence`，事实账本和题目记录两套数字；重放时还会重复发。现在只在 `substantive_attempts` 实际增加时发（`_apply_problem` 返回第三个值）。
  - `follow_up_question` 与 `content` 都是给孩子看的文字，容易出两个问题，且与 `next_subgoal` 无约束。v4 删掉该字段（模型返回也丢弃），提示词写明追问写在 content 里、`next_subgoal` 就是 content 所提问题的目标。
  - `redirect` 正文本身是带回任务，系统再补 REMINDER 会重复，现在不补。
- 清理（P2）：删 `history_ref`（校验后从未被读）、`Verdict.history_ref`、`TutorToolbox.authorized_refs`、`check_authority`/`vet_candidate` 的 `has_work_input`、`ProblemAssessment.same_problem`（恒为 True，换题由调用方在 `advance()` 前处理）。`Topic` 只含模型可写的两个值，`"chat"` 只是派生属性的返回值。`student_move` 进 `tutor.turn.result`（`tutor.student_move`），原来 request_hint/request_answer 没有任何消费方。
- 版本：契约 `tutor-turn.v4`，提示词 `tutoring.turn.system.v8`，组件 `tutoring.turn@v8`、`tutoring.leak-judge@v3`、`tutoring.visual-leak-judge@v2`，摘要锁同步。
- 测试：新增的 6 个工作流用例（放弃旧题后判官仍可见、无证据 attempt 不发事实、重放不重复发、误填 submitted 仍计提示、redirect 不重复提醒、受保护时 clarify 不能带答案）先在旧代码上确认全红，再改绿；单测补 clarify 检查、progress 归属、v4 删除字段被丢弃、判官摘要拼装、depth 只对 answer。全量 512 passed。
- 未做：离线评测 K=5 对照没跑（需要真实模型额度）。提示词改了 4 处（删两个字段、progress/evidence 归属、next_subgoal 定义），按 `eval-offline.md` 发布前应人工跑一次对照。
- 坑：`test_tutoring_workflow_usecase.py` 里两个 `history_ref` 用例在删字段后仍然是绿的（`extra="ignore"` 静默吞掉），删字段时要主动找这类"假绿"测试改掉或删掉。
