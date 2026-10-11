# 答疑：非作业轮的 `confirm` 被误判为 fallback

日期：2026-10-11

- 现象：答疑中孩子回答了模型自己提的选择（「壮阔宏大的」「是的，是的」），孩子却看到固定文案「我这次没能整理出回答……」。
- 根因：`check_authority` 对所有 `act=confirm` 要求 `progress=solved`。该规则本意是防止对未完成的作业"盖章"，但模型也把 `confirm` 用于「确认你说的是这一句」「看来你更喜欢……」这类非作业轮，此时没有 `progress`，整轮被判 `confirm_without_solved` 并走通用兜底。提示词只列了 `confirm` 这个词，没定义它的专门含义。
- 修复：`confirm_without_solved` 只对作业轮生效（`work_product_help` / `is_assignment_content` / 同一未结题的作业）。答案保护红线不变。
- 测试：`test_confirm_of_a_non_assignment_reply_is_not_replaced_by_the_fallback`（复现）；作业轮 confirm 未 solved 仍被拒（原测试与评测测试保留）。评测里原先把这个故障当成「预期的 fallback」的测试已改为新语义。
- 提示词：`tutoring.turn.system` 升到 v2（组件 `tutoring.turn@v2`），写明 `confirm` 只用于确认作业解答已正确（progress=solved）、孩子在回答上一轮选项时视为已选定不再确认、对象不明才 clarify 且同一对象最多问一次。摘要锁已更新。
- 离线评测（qwen3.7-plus-2026-05-26，K=5，16 个 proposed 用例，改代码+提示词后一起测）：采样通过 61/80 → 70/80；`confirmation` 用例 0/5 → 5/5；fallback 原因里不再有 `confirm_without_solved`（剩 `answer_marker` 3、`leak_detected` 1）。局限：用例都是 proposed、无 confirmed，样本小；代码与提示词同时改，无法分开归因；仍有 `turn-97103aaf-02`（0/5）等失败用例，与本次无关。结果在 `var/evals/after-confirm-fix.json`（不入库）。
- 排查方法：本机 `duxue-server/var/agent-llm-audit.jsonl` 按 `trace_id` 看每轮模型原文；被代码拒绝的候选在这里能看到，但最终展示的兜底文案不在这里。
