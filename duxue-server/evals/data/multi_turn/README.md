# 多轮评测

每个 JSON 是一段带学生反馈分支的合成会话，使用共用 `dialogue-eval.v1` 消息格式和 `generated_history` 执行模式。字段、状态来源和运行边界统一维护在[离线评测设计](../../../../docs/technical/eval-offline.md#44-合成连续对话)。多轮与单轮结果分别统计；人工复核前标签为 `proposed`。
