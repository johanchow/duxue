# 规划拒绝要能从日志看出字段和值形态

日期：2026-10-06

App 把 `/companion/turn` 的任何失败都显示成「这条消息暂未送达」。先前只有 409 会写 `companion.turn.rejected`，开始时间这类 400 只留在访问日志里，看不到是哪个字段、值长什么样。

现在两类拒绝都会进 `duxue.agent.audit`，并带上当前 trace：

- `companion.turn.rejected`：所有 HTTP 拒绝。稳定码来自固定文案或 detail.code，例如 `invalid_start_at`、`thread_version_conflict`。不写 detail 原文，避免把候选任务标题打进日志。
- `planning.input.rejected`：澄清槽或候选名称校验失败时额外记录 `planning.field`、`planning.rejection_code`、`planning.value_shape`。形态只分 clock / iso / text / int / list / object / empty 等，不记录原始回答。

钟点 `07:41` 会记成 `field=start_at`、`value_shape=clock`。完整 ISO 时间记成 `iso`。
