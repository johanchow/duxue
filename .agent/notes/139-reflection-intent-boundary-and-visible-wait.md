# 复盘意图边界与可见等待回复

日期：2026-10-21

- 现象：Ward 连续询问如何获得老师信任的例子，`companion.intent` 提议 `reflection`；复盘 Workflow 因没有 `review_date` 返回 `needs_self_review`，该状态没有正文，Coordinator 不写 companion 可见消息。HTTP 200 但页面无回复。
- 根因：旧提示词只说 `reflection` 是“复盘今天的学习”，并要求延续当前 focus；没有把“明确回顾自己今天的学习”作为必要条件。首次误路由建立 reflection focus，后续追问继续命中。
- 决策：`reflection` 仅限明确总结、复盘、反思或回忆自己今天的学习状态、内容或目标；提问、求解、理解知识、请举例进入 `tutoring`。focus 只辅助理解省略和指代，本轮明确转换意图时切换。提示词升级为 `companion.intent.system.v2`；不写具体话题词表或正则路由。
- 兜底：ReflectionWorkflow 等待自评时返回有正文的引导语，让结果经现有 transcript 机制展示，避免静默成功。
- 验证：先有失败测试复现无可见正文；修复后服务端全量测试 569 passed，离线评测数据格式通过。真实模型调用在受限网络环境返回 `model_transport_error`，新增真实提问评测样例供后续联网环境重跑。仓库全量 Ruff 当前有大量既存告警，未在本次扩大范围清理。
