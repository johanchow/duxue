# TaskReferenceResolver implementation

日期：2026-09-18

- `PlanIntake` prompt 与输出不再允许模型看到或生成 Task ID；模型只给 `task_reference`、时间/顺序字段和任务标题。
- `PlanningDomainService.resolve_task_references()` 在 `register_tasks()` 前执行：唯一的规范化名称匹配转成已有 Task patch，多个候选只返回 `ambiguous_target_task`，零候选才可成为新任务。
- 兼容旧 `planning_items` 时保留显式 ID，但仍验证它属于当前 Ward、未完成且未排期的 Task。
