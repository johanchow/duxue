# Companion Interaction Protocol

> 日期：2026-09-16

## 决策

不为读学引入 AG-UI / Generative UI。Companion 与 App 之间使用自有信封 `companion-interaction.v1`，写在 [domain-companion.md §5.2](../../docs/technical/domain-companion.md)。

- 历史气泡：`CompanionMessage` 只含 text + media_refs。
- 当前屏：关闭的 `kind` 清单 + `parts` + `allowed_actions` + `object_ref`。
- 业务数字：始终从目标 Context Query 刷新（如 `GetPlanDraft` 的全部未完成任务列表）。
- 用户动作：只执行上一轮 `enabled` 的 `StructuredWardCommand`；模型不能发明 kind 或按钮。
- 流式：仅 `TEXT_DELTA` / `INTERACTION_READY` / `RUN_FINISHED` / `FAILURE`。

当前 `interaction: dict` 与 `planning_confirm` 视为兼容窗口，不再扩展平行字段。
