# 127 — 生产切到 duxue-prod

- 本地 `.env.prod` 已 scp 到 ECS `/home/duxue/duxue-server/.env.prod`；旧文件备份为 `.env.prod.backup-20261018T090959`（当时误指 `duxue-test`）。
- 线上容器已 force-recreate，`DATABASE_URL` 指向 `duxue-prod`，`APP_ENV=production`。
- `duxue-prod` 业务表原为空、停在 `20260804_02`。`08`/`10` 的 `create_all` 与后续 revision 冲突：整链 `upgrade head` 会在 `25` 因列已存在失败并整段回滚。做法：`upgrade 20260830_10` 后 `stamp 20261010_25`。
- `10` 的 drop 名单补了「先按当前 metadata 逆序 drop」，否则 `tutoring_problems` 会挡住 `tutoring_sessions`。
- 切库后线上是空库；此前 ECS 实际写在 `duxue-test`，数据不会自动过去。
