# 真实图片核对用例的评测边界

日期：2026-10-29

事实源：[`real_regression/multiphoto_trace_4d700e7f.jsonl`](../../duxue-server/evals/data/real_regression/multiphoto_trace_4d700e7f.jsonl)。

- 从 Langfuse trace `4d700e7f2a675c82355436ad9de8e774` 的答疑主调用提取最近 8 条原句与本轮新图；原图只保存在本机 `duxue-server/var/eval-assets/trace-4d700e7f-current.jpg`，遵循评测资产不入 Git 的约定。
- trace 中选图检查为本轮图片 1，主调用及独立泄露检查均只收到这张图；图里第 2、3 题可见作答，第 4 题仅露出上沿。用例期望只核验可见范围，避免复用历史第 4 题结论。该语义要求需要人工复核，现有确定性 grader 只作弱断言，标记 `proposed`。
- `ENV_FILE=.env .venv/bin/python -m evals run --component tutoring.turn --case turn-4d700e7f-image-review --samples 3 --workers 3` 的真实重放为 1/3 通过、2/3 `fallback(leak_detected)`；这暴露了图片作答核验与泄露裁判之间的不稳定性，不能因为 trace 原轮放行就把该样本标成 `confirmed`。
