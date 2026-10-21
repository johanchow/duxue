# 复盘意图只接受自我回顾

日期：2026-10-21

- 现象：Ward 问「我最近都在问什么问题？」时，`companion.intent` 提议 `reflection`。复盘流程没有 `review_date`，直接返回固定引导「如果想复盘今天的学习……」，没有查询以往原句。Trace `3c685f771af2966106c44b3b684ad1dc`。
- 根因：`companion.intent.system.v2` 把「回忆自己今天的学习内容」划给 reflection，模型把「最近问过什么」当成回忆学习内容。
- 决策：reflection 只在孩子讲自己做过的事情、感想、思考，或以后会怎样时选择，或者孩子明确说明要总结或复盘。询问最近问过什么进入 tutoring。提示词升为 `companion.intent.system.v3`，组件版本 `v3`。不新增关键词路由。
- 验证：提示词锁与组件版本单测；新增 `scene_routing/recent_questions.jsonl` 供离线评测重放。
