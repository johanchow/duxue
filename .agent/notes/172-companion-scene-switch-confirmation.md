# Companion 跨场景切换独立确认

日期：2026-10-30

- 现象：trace `82e3ab30801d39d3b625afbb8c823173` 中，孩子在竖式答疑中回答“最后结果二百三十八。”；`companion.intent@v7` 已收到最近对话和 tutoring focus，却提议 reflection。原路由器只验证闭集标签，直接 handoff，复盘工作流随后返回自评引导。
- 决策：仅在已有 focus 且初次模型提议另一业务场景时，调用独立的 `companion.scene-switch@v1`。该组件使用不同模型、原句与同一授权窗口，返回严格布尔值。明确允许才 handoff；否决、非法输出或模型异常继续原 focus，并区分记录 route reason。安全短路、已验证 UI 指令、无 focus 和同场景续接不加调用。领域定义见 [`docs/technical/domain-companion.md`](../../docs/technical/domain-companion.md#三coordinator-process-manager)。
- 验证：先写失败测试；服务端全量 668 passed，受影响文件 Ruff 通过，`git diff --check` 通过。真实模型用无敏感信息的算术续接和明确复盘样例分别返回 `False`、`True`。沙箱内 DNS 不通，经批准的联网验证成功。
- 限制：该判断只有在初次意图模型提出跨场景时才运行，不能修正无 focus 的初次误分；模型可用性故障时继续原场景，可能暂时挡住一次真实切换。后续可按 `scene_switch_rejected` / `scene_switch_unavailable` 观测误判与故障率。
