# Task reference resolution for Planning patches

日期：2026-09-18

- v1.4 将已有任务的局部排程更新定义为“任务引用 + 安排字段”的语义分支，不以“改/调整”等关键词判断。
- 模型只输出无 ID 的 `TaskReferenceCandidate` 与字段 patch；`TaskReferenceResolver` 按受控 task_id、澄清槽位、UI 焦点、名称唯一匹配的固定优先级绑定。
- 非唯一或未解析的引用进入 `target_task_id` 澄清，不能创建同名 Task；唯一已有引用优先于任何模型产出的同名新任务候选。
