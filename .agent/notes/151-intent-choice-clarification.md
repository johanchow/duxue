# 不明意图的三选一澄清

日期：2026-10-22

- 现象：`unclear` 原本只写固定文字，孩子必须重新表达；直接重发原话并附 `route_hint` 会在 transcript 中复制一条原消息，且卡片无法安全判断是否仍有效。
- 决策：Coordinator 给 `unclear` 回复签发 `intent_choice`，三个 `choose_intent` 动作固定为管理任务、总结思考、提问探讨。回复写入 transcript 的 `interaction_ref`；App 只在该回复仍是当前 Thread 末尾消息时展示选项。
- 权限：选择绑定最新回复的 `interaction_id`、完整 payload、Thread 版本及原 Ward 消息。服务端从原消息恢复文本和附件供目标 Workflow 处理，transcript 只新增“选择：…”记录。伪造、过期、重复点击返回 409；同一 `command_id` 的网络重试走现有幂等结果。
- 验证：服务端测试覆盖三目标、旧选择、伪造选择、带图续接；全量 pytest 609 项通过。Flutter 聊天页测试覆盖显示、点击、失效；全量 Flutter test 90 项与 analyze 通过。改动服务端文件 Ruff 通过，`git diff --check` 通过。
