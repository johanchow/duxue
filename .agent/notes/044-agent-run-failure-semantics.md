# Agent Run 失败语义嵌入点

- Run 的失败、超时、取消与恢复不是独立 Runtime 章节，而应同时出现在生命周期、状态触发矩阵、Use Case、传输契约和验收场景中；这样同一状态名称和责任边界可被实现与测试。
- `failed` 表示当前 attempt 内无法自行消解的模型、工具或校验失败；`timed_out` 表示 Run deadline 或声明预算耗尽；`cancelled` 只能来自受权 Ward 的显式取消。SSE/HTTP 断开仅是传输中断，不能隐式取消业务 Run。
- Gateway 可在当前 attempt 内按 Policy 做有界技术重试；只有重试耗尽后的 Outcome 才改变 Run 生命周期。Ward 显式 retry/resume 会产生新 attempt，迟到 Outcome 仍受 run/turn/attempt/focus fence 限制。
