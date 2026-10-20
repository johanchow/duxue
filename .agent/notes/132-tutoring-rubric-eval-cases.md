# 答疑 rubric 评测用例

日期：2026-10-19

- 决策：高阶教学场景用合成 `rubric` Case 补进 `evals/data/tutoring_turn.jsonl`，不带 `guard` 标签（现有测试把 `guard` 限制在 6 条）。公开数据集只提供维度和失败形态，学生句和历史是新写的，原文不入库。
- 断言仍是结果类别和终答字面量。阶段、参考教师回复、语气写在 `note`，当前判分不读。全部 `proposed`，复核前不进 primary。
- 坑：`content_not_contains` 是子串。禁用「correct」会命中 “incorrect”；禁用单个「11」会命中把选项复述一遍的合法引导。终答要用长短语，不要用单个数字或单词。
