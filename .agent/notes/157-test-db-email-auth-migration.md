# duxue-test 邮箱认证迁移（2026-10-24）

- 用户要求把 `.env` 指向的 `duxue-test` 测试数据库也升到最新版本；确认目标为 `duxue-test`、`APP_ENV=test`，执行前版本 `20261010_25`，目标 `20261024_28`。
- 执行 `ENV_FILE=.env .venv/bin/alembic upgrade head` 成功；随后 `alembic current` 为 `20261024_28 (head)`。
- 单独只读检查确认 `email_auth_challenges`、`email_auth_failures` 均存在，`user_guardians.password_hash` 已移除。
- `alembic check` 报出的待删除对象只涉及 LangGraph 自管的 `checkpoints`、`checkpoint_blobs`、`checkpoint_writes`、`checkpoint_migrations` 表及其索引；这是现有外部 checkpoint schema 与应用 ORM 的元数据差异，并非本次邮箱认证表缺失。未删除这些表。
- 认证设计和生产配置/迁移记录见 [156-guardian-email-code-auth.md](156-guardian-email-code-auth.md)。
