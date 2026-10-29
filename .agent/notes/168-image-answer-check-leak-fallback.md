# 168 图片作业答案核验被泄露门禁降级

日期：2026-10-29

- 生产复现：Ward 问“帮我看看截图图片里面的两个题目的答案有没有做对？”后，主答疑模型已从图片得出第 2 题正确、第 3 题的思路填空错误的候选；候选解析成功，没有模型或图片请求错误。
- Langfuse / Grafana 证据：每一版候选（主模型、带 `泄露：` 反馈的重试、备用模型）均由 `tutoring.leak-judge@v6` 判为 `final_answer`，`tutoring.exit_gate` 返回 `leak_detected`，最后 `tutoring.result` 投影固定 fallback。该会话两次追问均如此。
- 根因：候选的 `turn.evidence` 含图片中孩子已写的列式和答案，但文字泄露裁判只收到 `problem_summary`（最近的口述/文本），没有题图转写或该 evidence。因此它无法识别“算对/填错”是对孩子已提交作答的核验，只能按未提供证据的最终答案处理。`relation=new` 又会在 `check_authority()` 中令 `claims_work` 为真，即使入参 permit 未保护也强制进入 fail-closed 文字裁判。
- 决策（2026-10-29）：不为所有图片建立题图 OCR/VLM 转写或摘要流程。只有现有出口规则已判定候选需要作业泄露审核时，才把本轮与同一线程可见窗口中已授权的原图传给独立视觉裁判；非题目图片不增加处理。原图用于裁判自己辨认题面与孩子已写作答，不能成为模型绕过权限的声明。图片模糊、仅有题面、选择/判断题或裁判异常均继续 fail-closed；图像字节不写入遥测。
- 上线前调试（2026-10-29）：首版给裁判选用的 `qwen3-vl-flash-2026-01-22` 在当前 DashScope OpenAI-compatible Chat Completions endpoint 返回 HTTP 404，因而被 `QwenLeakJudge` 转为 `leak_check_failed`。已改为与主答疑模型独立、同一 endpoint 已支持多模态输入的 `qwen3.8-flash`（组件 `tutoring.leak-judge@v8`）。真实图片离线用例 `worked-image-answer-confirmation` 用该模型采样 3 次，均返回有效的 `leaks=false`；结果保存在本机忽略目录 `duxue-server/var/evals/20261029-133115-first-image-judge.json`。
- 路由回归（2026-10-29）：两条“看一看/照片里的全部题目有没有都做对”被 `qwen-flash` 错判为 reflection；路由器会无条件采纳格式正确的模型标签，首次 handoff 后下一轮继续该 reflection run。按产品边界，这类图片题目核验均属 tutoring。仅收紧 `companion.intent` prompt 到 v7：reflection 必须有明确复盘/总结/回忆，或基于已叙述个人经历作改进反思；检查、核对、讲解、订正题目及“看一看全部题目”一律 tutoring。未增加二次裁决或改变路由逻辑。
