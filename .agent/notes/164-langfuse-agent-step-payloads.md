# Langfuse Agent 步骤输入输出

> 日期：2026-10-25

## 现象与原因

生产 trace `e8d7955f983209f8e5993b97673c1bae` 已有根轮次、generation 与工具正文，路由、workflow 和大多数 node/check 的 `input/output` 仍为空。前者是这些 span 的调用点没有设置 payload；后者部分在 `65a5b01` 才补齐，而该提交当时尚未进入生产 `main`。

## 决策

- 路由写入本轮内容、已有焦点及最终决定；workflow 写入授权的 `RunInvocation` 和 `WorkflowOutcome`。
- `traced_agent_node` 自动把函数参数和返回值投影为 observation。Pydantic、dataclass、基础容器展开；服务、数据库 Session、模型客户端等对象只记类型。节点内部已经写入专用 output 时不覆盖。
- 补齐剩余 check：工具预算、图结构、确认门禁、输出安全跳过、候选拒绝和配图丢弃。异常只记异常类型。
- 旧 trace 不回填；部署后应以新轮次验证 Langfuse，不能把此历史 trace 当作新代码验收。

## 验证

- 集成测试先复现 route、workflow、node 缺少 input/output，再验证三类 span 均有字段；答疑检查节点亦验证字段齐全。
- 服务端完整测试 `642 passed`；修改文件 `ruff --select I,UP035,SIM102` 与 `git diff --check` 通过。
