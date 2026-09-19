# Companion 确认卡与 409 恢复

日期：2026-09-18

- App 只在服务端交互明确为 `plan_confirm_list`、并带有启用的 `confirm_plan` action 时渲染“已记录（待你确认）”卡；任务入池或澄清交互不再借用该卡片。
- `GET /companion/threads/{id}/messages` 的 `thread_version` 是下一轮写入的并发令牌。客户端刷新 transcript 时必须同时更新并持久化它；只读取 `messages` 会导致后续反复发送过期 version。
- 确认收到 409 时，客户端立即撤销本地 action/draft 卡片，再尽力刷新投影和 transcript；不会自动重放一个可能失效的确认。
- `/companion/turn` 对协调器在 workflow 前拒绝的 409 写出 `companion.turn.rejected`。字段仅包括 rejection code、HTTP 状态和是否包含 thread/structured command，不包含 Ward 文本、thread ID 或 interaction ID，方便 Loki/Grafana 聚合且不泄露内容。
