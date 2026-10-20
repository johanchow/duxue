# 答疑离线评测分类与多轮用例

日期：2026-10-20

- 决策：`evals/data/` 下八个主类别各一个目录，单步 `cases.jsonl` + 可追加的 `supplement.jsonl`，多轮独用 `multi_turn/episodes.jsonl`。目录是唯一主归属，`tags` 仍表示交叉维度；`--category` 可定向校验和运行单步用例。
- 原有 63 条只迁目录，ID、正文、断言、状态未改，迁移后子集哈希仍为 `bf1f9e2efda35d59`。新增 27 条单步、24 段六轮自写多轮，全部先是 `proposed`；0 条 `confirmed`，不能当发布通过依据。公开数据只借鉴场景和失败形态；CoMTA 原文不进仓库。
- 多轮 runner 复用生产单步组件路径，将实际导师回复带入下一轮 8 句窗口；一轮断言失败就停止，避免预写学生续句与错误回复拼接。`student_on` 可按上一轮 outcome 选择学生后续句。题目状态由评测标注注入，尚非完整 Aggregate 状态迁移；字面断言也不能证明真实教学效果。
- 运行：CI 只校验和测假模型；真实模型 `run` / `run-episodes` 都是本机命令。旧 `guard` 标签仍为 5 条，新增答案保护场景不占原 `guard ≤6` 哨兵配额。
- 坑：拆目录后必须递归加载单步 JSONL，同时避开 `multi_turn/episodes.jsonl`；结果哈希须与加载内容而非路径关联。多轮哈希需覆盖分支、备注等全部 episode 字段，不能仅哈希每轮投影。
- 验证：`python -m evals validate` 为 90 + 24；服务端全量 pytest 557 通过，`git diff --check` 通过。人工复核仍待 Gate 2。
