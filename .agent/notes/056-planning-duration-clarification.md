# 计划任务预计时长缺失时的追问

> 日期：2026-09-16

## 现象与根因

Ward 通过统一 Companion 计划入口提出任务、却没有说明预计时长时，`PlanIntakeItem.planned_minutes` 的 Pydantic 默认值会把缺失字段静默变成 30 分钟。因此草稿看起来完整并可进入审阅，违背“只提取 Ward 明示意图”的计划约束。

## 决策

- `planned_minutes` 以 `null` 表示未提供，绝不推断默认值。
- 解析结果缺少时长时，强制改为不可确认并返回单一问题：请 Ward 补充对应任务的预计时长。
- 不完整草稿保留 `pending_fields=["planned_minutes"]`，确认仍由领域服务拦截；下一轮解析将活动草稿带入上下文，避免 Ward 只回答“20 分钟”时丢失任务名。
- 旧的直接保存计划接口同样拒绝缺失时长，避免绕过统一入口再次写入 30 分钟。

## 验证

- `duxue-server/.venv/bin/pytest tests -q`：130 passed。
