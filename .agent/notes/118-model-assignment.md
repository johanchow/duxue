# 模型分配切换

日期：2026-10-11

- 决策：JSON 组件按任务换到百炼当前档位，并在调用处关闭思考。`tutoring.turn`、`planning.intake`、`task.intake`、`reflection.advice` 用钉死的 `qwen3.7-plus-2026-05-26`；`planning.reply` 用 `qwen3.8-flash`。帧分析默认 `qwen3-vl-flash-2026-01-22`。发音点读仍是标准 TTS。
- 实时 ASR 保持 `qwen3-asr-flash-realtime`。钉到 `qwen3-asr-flash-realtime-2026-02-10` 后，北京业务空间会在 `session.update` 或首段音频后直接断开，没有关闭帧。
- 未换：`companion.intent` 仍是 `qwen-flash`，`tutoring.leak-judge` 仍是 `qwen-plus`。决策模型 `decision-model-preview` 更贴这两处的闭集判断，但它走 `/systemone`，而且是预览，内容安全可能直接拒绝作业文本。泄露判断必须和答疑主模型不同型号。
- 坑：思考模式会吃掉 `max_tokens`，JSON 可能被截断。Chat 调用用 `extra_body.enable_thinking=false`；帧分析的 batch JSONL 把 `enable_thinking: false` 放进 body。
- 部署：线上若已设置 `VLM_MODEL_NAME` 或 `ASR_MODEL`，代码默认值不会覆盖环境变量。
