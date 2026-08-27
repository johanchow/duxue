# PostgreSQL assignment session migration

- 线上 PostgreSQL 的 `study_sessions` 停在 Alembic `20260823_06`，缺少 `assignment_id`；计划确认本身可成功，但任务池刷新会读取该列并返回 500，导致 App 误报确认失败。
- `20260825_07_assignment_sessions` 不能在 PostgreSQL 使用 `batch_alter_table(recreate="always")`：新外键必须命名，且重建 `study_sessions` 会被 `study_messages.session_id` 的外键引用阻止。
- 该迁移对 PostgreSQL 使用原生 `ALTER TABLE`（放宽 `plan_item_id`、新增 `assignment_id`、命名 FK 和索引）；保留 batch 分支给 SQLite。实际数据库已成功升级至 `20260825_07 (head)`，服务端 27 项测试通过。
