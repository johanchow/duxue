# PlanIntake prompt 花括号与失败可见性

日期：2026-09-19

- PlanIntake 的提示词是 Python f-string。若在示例 JSON 中写字面量花括号，必须使用 `{{`、`}}` 转义；否则运行时会被解释为 Python 表达式，可能在模型调用前以 `NameError` 失败。
- Coordinator 捕获 workflow 异常后不能只记录 `failure` 并返回空 interaction：HTTP 200 会被 App 当作成功，用户看起来像 AI 没有回复。失败 Outcome 必须含受控 `companion-interaction.v1` error 文本，使 transcript 与当前响应都能显示可重试提示；底层异常细节仍只留在受限审计数据。
