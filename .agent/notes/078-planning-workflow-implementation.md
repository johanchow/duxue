# Planning Workflow v1.7 实现收口

日期：2026-09-20

- 按 `docs/technical/domain-planning.md` v1.7 补齐多操作 Planning 流程：新增、内容修改、安排、显式暂不安排、名字/耗时/目标/开始时间澄清，以及单轮独立操作结果。
- 模型只输出无 ID 的操作和 slot 答案；`TaskReferenceResolver` 在受权任务集合中绑定目标，服务端校验多选候选集合，未知或歧义引用不会创建 Task。
- 正式确认同时重验草稿版本、Task 版本、日程基准版本、执行状态与完整时间冲突。Task 使用 SQLAlchemy 乐观锁；正式日程保存当前 items 与 history；确认事务写 `LearningFactRecorded.v1` 和 `PlanConfirmed.v1`。
- 同一 Ward/日期只保留一个 active PlanDraft；确认后可建立修订草稿。修订加载原正式项，确认前不改变原计划或已排期 Task，已开始计划拒绝修订。
- 兼容 `/plans` 写入口改为保存 PlanDraft；确认必须携带 `draft_id + expected_draft_version`，缺少时间或存在冲突不能提交。
- Alembic `20260920_19` 增加 Task 版本、DailySchedule 当前项/历史，并把 PlanDraft 唯一约束改为 active partial unique index。迁移只从带完整时间证据的 confirmed draft 回填；存在修订历史时拒绝有损降级。
- 回归测试覆盖缺名字、缺开始时间、目标歧义与越权、多目标原子修改、局部成功、耗时变化后重排/冲突、Task 并发写、确认 stale、正式计划修订、迁移回填与有损降级保护。

验证结果：

- `pytest tests -q`：170 passed，只有既有 `system.py` FastAPI `on_event` 弃用警告。
- 新增 workflow 场景测试：22 passed。
- 新增/重构 Planning 文件的 Ruff 检查与 `git diff --check`：通过。
- 临时 SQLite 从空库 upgrade head、`alembic check`、downgrade 到 `20260918_18`、再次 upgrade head：通过。
- `.env` 指向的数据库已升级到 `20260920_19 (head)`。该库的全局 `alembic check` 仍报告 LangGraph 自管的 `checkpoints` / `checkpoint_blobs` / `checkpoint_writes` / `checkpoint_migrations` 表不在 SQLAlchemy metadata，属于既有 schema 管理边界问题，不是本迁移产生的差异。
