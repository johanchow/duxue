# 答疑意图分流与发音看图

日期：2026-10-07

事实源：`docs/technical/domain-study.md` v2.5 §1.1 与 §4.6；Companion 只在场景路由后链到该节。

- Companion 的 `tutoring` 不是解题。进入答疑后，另一次无状态结构化调用提议 `TutoringIntent`：`problem_solving`、`curiosity`、`conversation`、`safety`、`pronunciation` 之一。非法提议不猜测，沿用 Companion 的 `unclear`。
- 「读出发音」是已验证的 `tutoring_intent=pronunciation`，跳过这次提议。不用关键词做主解释器，也不把发音加进 Companion 场景枚举。
- 发音 profile 的已授权图片以 `data:<mime>;base64,...` 放进 `image_url`。对象存储路径只用于核对和读取，不写进给模型的文本。
- 实现：`TutoringWorkflow` 在解题循环前调用 `QwenTutoringIntentProposer`；已验证的 `tutoring_intent=pronunciation` 跳过。非法提议复用 Companion 的 unclear 回复，不打开学习会话。发音模型用户消息由 `pronunciation_user_content` 组装。
- 答疑意图说明按路径写清边界：没看懂作业题是 problem_solving；材料里、不属于这道题的词句释义是 curiosity；pronunciation 只在当前这句明确要朗读或发音时选用。最近原句只认指代，不把上一轮的发音意图延续过来；接着问中文意思或翻译仍是 curiosity。
- 发音调用带上与计划录入相同的最近原句，并重发该窗口里当前 Ward 的已授权图片。结构非法的唯一次重试附带校验错误。
