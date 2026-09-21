# Planning Agent Loop 不签发空目标候选

日期：2026-09-21

- 现象：Ward 先说“英语听力换到十九点开始”时，服务端为 `target_task_ids` 签发了空 `candidates/candidate_task_ids` 的澄清槽；下一轮“加一个英语听力要三十分钟，从七点开始”被模型当成 slot 回答，adapter 用名称匹配空候选后抛 400，随后客户端旧 `expected_thread_version` 重试触发 409。
- 根因：实现仍是“一次 LLM intake + 大函数补规则”的过渡态，引用解析没有把 `no_match` 和 `ambiguous` 分成不同 observation。空候选被错误建模成 Ward 可回答的问题。
- 修复：`PlanningOperations.apply_operations()` 在目标引用解析时，只有存在受权候选才签发 `target_task_ids`；没有候选或引用未命中时将该操作标记为 `rejected`，独立操作继续执行。入口同时清理历史空候选 slot，避免旧坏状态继续卡住草稿。
- Adapter 兼容：模型若回填历史空候选 `target_task_ids`，该 answer 会被忽略，不再提前 400；新 operations 继续进入 use case，由确定性工具 observation 决定结果。
- 规避：以后新增 Agent Loop 工具时，工具必须返回 `unique/ambiguous/no_match/rejected` 等受控枚举；不得把不可回答的状态包装成澄清问题交给模型或用户。
