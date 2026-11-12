# 只读初始化快照

`2026-11-11/` 是迁移到 Langfuse 前的 41 个用例，供首次导入与无网络协议回归使用，**不再维护新用例或期望**。

唯一维护入口是 Langfuse Dataset。`python -m evals run` 只读取云端数据。迁移命令按稳定 ID 幂等创建，拒绝覆盖已编辑内容；不会把此目录持续同步到云端。

评测协议与命令见 [离线评测设计](../../../docs/technical/eval-offline.md)。

2026-11-12：云端已归档 `turn-visual-leak-00` 和 `episode-image-switch-and-correction`，当前执行集39例。本目录保留迁移时41例原貌，不能用它推断当前有效用例数；迁移命令遇到已有归档记录不会重新启用。
