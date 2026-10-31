# Langfuse observation 用配置身份筛选

决定：每条导出的 observation 写 `kind`、`kind_id`、`kind_version`，并保留 `workflow_id`、`node_id`。不把所有 span 都标成 agent 或 gate。

原因：节点 ID 和定义 ID 不同，例如 `tutoring-vet.text_leak` 引用 Gate `tutoring.leak-judge`。Workflow、代码步骤和摄像模型调用也不是 Agent/Gate。单独的 `kind` + `kind_id` 会丢掉流程位置，或把不是配置对象的调用标错。

`external` 只用于目录外的模型调用，`kind_id` 是操作名。同一 Agent 的主模型和备用模型靠 `component_id` 区分。
