# Planning 旧澄清覆盖本轮排程回复

日期：2026-09-19；范围：诊断，未修改业务代码。

## 证据与边界

- Grafana Tempo trace `371fdd478fa7014bd4cd9c51d54f3556`：入口以 `validated_route_hint` / `start` 路由 Planning；Run `3ab17c6d-4895-4bda-9f12-5a8054f5498b` 调用 `plan_intake`（qwen3-vl-flash，2146 ms，711/156 tokens），最终 `waiting_for_ward`，无 fallback。不是入口跳过模型。
- 对应时间窗口 Loki 未返回日志；Tempo 未记录 intake 原始 JSON。限定只读数据库查询在沙箱内外均因 DNS 解析失败，无法确认现场草稿的数学时间或旧英语槽位来源。
- 本地 SQLite 内存复现：预置数学试卷（40 分钟）与英语听力缺时长 batch；模拟模型正确返回数学试卷 `start_at=19:00+08:00`。真实 Adapter + Graph 保存数学时间，却回复“还需要补充 ‘英语听力’ 的预计时长”。两个断言通过；未调用外部模型、未修改业务数据库。这证明模型正确也足以触发该症状，不证明现场模型具体输出。

## 实现问题

- `PlanningWorkflowAdapter.invoke()` 只要发现 active clarification batch，就追加草稿全局 `planned_minutes` pending；草稿按 Ward + 本地日期加载，不限定 Run。
- `PlanningDomainService.save_draft()` 保留旧 batch；Graph `prepare_review` 遇任意 pending 就返回 `needs_input`。
- Adapter `_clarification_outcome()` 仅从 batch 的 slot 标题生成固定追问，不接收本轮已应用 patch 或模型回复。因此历史待补事项覆盖本轮明确意图的反馈，且全局 pending 阻止其它有效项确认。
- 设计依据只维护于 [Planning 领域设计](../../docs/technical/domain-planning.md)（Clarify 不得抢占本轮安排意图）与 [Companion 协议](../../docs/technical/domain-companion.md)。

## 后续修复方向

按本轮已验证变更生成回复，区分当前目标的阻塞字段与其它任务待补信息；历史槽位保留但不独占回复。补“数学排程 + 英语缺时长”的跨轮回归，同时校验任务 ID、时间、回复和确认范围。为引用决议/patch 写入增加不含原文的 trace 属性，便于区分模型提取、任务绑定、回复选择三类故障。
