# 115 答疑候选的结构恢复边界

日期：2026-10-10

现象：最近 22 条 `tutor_turn` 原始回包均为可解析 JSON，但模型会把 `pronounce` 写进 `question_kind`、在 `clarify` 中附带不完整的 `lesson`，或直接返回空字符串。此前坏 lesson 会在 Pydantic 创建候选前失败，导致本可展示的澄清也被固定回退文案替代；网关层的空字符串也不会进入原有的结构重试。

规避：

- 在候选预校验阶段，仅当 `act=clarify` 才丢弃 `lesson` 与摊平的发音字段；澄清不投影发音卡，且对象未确认时保留它是安全的。
- 仅对 `clarify` 和 `pronounce` 把精确错位值 `question_kind=pronounce` 修成 `chat`。`answer`、`hint` 等能影响作业保护的 act 不猜测分类，仍走一次修复重试或回退。
- Provider adapter 报 `invalid_model_candidate`（包括空字符串和坏 JSON）时，和 Pydantic 结构错误一样只重试一次；第二次失败仍固定回退。
- 结构恢复只能删除不投影的附带字段或修复唯一无歧义的错位枚举；不得生成、替换或扩大面向孩子的答案、lesson、作业状态或许可。
