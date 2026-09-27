# Study 提示等级与会话边界

学习执行不再改 Planning 的 Task 状态。开始、暂停、继续、完成只写 `StudySession` 和计时区间。

答疑等级由 `HintingPolicy` 决定：新题从 L1 起，满三次未通过才允许 L4。直接索答不写 Fact。互动事实使用 `tutoring.attempt_recorded`；记忆结算仍接受旧名 `tutoring.ward_attempt_recorded`。
