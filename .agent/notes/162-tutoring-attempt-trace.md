# 答疑失败轮的完整 trace

日期：2026-10-24

- 现象：18:25 的三次 `leak_detected` 只在 Grafana/Langfuse 留下模型输出长度与摘要，无法看到三版原文和审核原因。该轮发生于正文采集版本生产启动（19:08）之前；历史正文不能回填。生产原文审计开关也未启用。
- 已有：当前代码在模型 generation 保存实际消息、原始回复，在根 `agent.turn` 保存 Ward 输入和最终展示回复；组件版本可查。
- 缺口：同一轮的主生成、重写、备用生成与各自审核仅靠时间顺序对齐；审核节点缺少完整输入、结构化结果及原因；generation 缺少显式提示词 ID。结构校验被拒时同样缺少节点级原因。
- 修复：每次尝试建立 `tutoring.attempt` 父节点；结构检查、出口检查、文字和图审核及最后的输出安全审核写入各自的 input/output；记录经过白名单校验的泄露原因码；模型 generation 记录 `ai.prompt_id`。原始候选仍以对应 generation 为准，最终展示仍以根轮次 output 为准。
- 验证：先写三次尝试同 trace 的复现测试（红），再完成实现；覆盖审核输入、原因码和父子关联，并用真实 OpenTelemetry + Langfuse 转换器验证 generation 的消息、提示词 ID 和原文。服务端全量 `642 passed`；修改文件的 `ruff --select I,UP035,SIM102` 与 `git diff --check` 通过。生产验证应使用部署后的一次受控新轮次，确认 Langfuse 与 Grafana 实际可读，不能用旧 trace 证明新代码失效。
