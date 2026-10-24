---
slug: langfuse-conversation-payloads
created: 2026-10-24
status: done
---

# Langfuse 对话与工具正文

## 目标与验收

- 每轮 Companion 根 observation 记录孩子本轮可见输入与最终展示回复，Session 能回放对话；clarify、安全回复与幂等返回也有正文。
- 每次模型 generation 记录实际发送的消息与模型原始回复；孩子上传的图片在根轮次和模型输入中作为 Langfuse Media 保留，供后续读取。
- 答疑工具（含预置指南）的 observation 记录实际参数和结果；没有执行的工具不生成工具节点。
- 答疑目标推进可直接核对模型候选 `next_subgoal`、规则处理后的 `active_subgoal` 与最终展示文案；成功提交后 Loki 写入目标和展示正文，回滚不写 `committed` 日志。
- 保持现有 session/run 关联、token、Grafana 导出与测试可用，更新可观测性文档。

## 实现计划

1. 在 telemetry 添加 Langfuse observation input/output 写入接口，接入根轮次与模型调用。
2. 在 Companion Coordinator、模型组件及 Tutor Toolbox/预置指南接入各自正文。
3. 先添加回归测试，实施后运行相关测试、完整服务端测试、lint、diff review。

## 完成度

- [x] 回归测试
- [x] 根轮次、模型与工具上报
- [x] 文档与笔记
- [x] 完整验证与 review

## 备注

用户已明确授权上报孩子问话、模型回复和工具正文，作为本次数据策略变更依据。
用户后续要求图片可供 MCP 完整分析；OSS 临时 URL 会过期，因此使用 Langfuse SDK 自动提取并上传 `data:` 图片，trace 留下可解析 Media 引用。Grafana 导出副本移除图片字节。
追加验证：完整服务端测试 639 passed；修改文件 `ruff check --select I,UP035` 与 `git diff --check` 通过。
