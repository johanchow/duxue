# 真实对话回放接入与首次运行

日期：2026-10-30。

- 用户明确要求继续运行 `conversation_replay/`，解除先前不执行的限制。沿用已审阅的配置，未改原始消息、候选或期望。
- 接入契约与引用校验、目录分派、统一 `run-conversations` CLI；逐检查点固定原历史，permit 使用快照，不将新回复回灌。原候选门禁使用其原始 `task_title/problem/reply`，不使用独立判官执行器的默认题面。
- 主流程仍走生产 runner 与出口检查；新增可选 permit 注入只供真实快照回放，原单步路径不变。报告区分最终展示正文和被拒草稿，保留门禁调用及修复过程。
- 参考回复和 criteria 没有自动语义评分器：自动结构通过保留 `passed=null/pending_review`；不能因未触发 fallback 就视为教学达标。独立门禁按 leaks/reason 对照标签。
- 先写失败测试（9 项均因缺适配失败），实现后评测模块 100 passed；服务端全量 728 passed。全量配置校验成功，种子哈希仍为 `7084bc6835908cf9`。
- 沙箱内首次运行全部连接失败，报告 `var/evals/answer-feedback-conversation-20261030.json` 不作质量依据；经联网权限批准后重跑，报告 `var/evals/answer-feedback-conversation-20261030-network.json`，每检查点采样 3 次。
- 联网结果：三个固定候选门禁检查共 9/9 符合期望。原 incorrect_confirmation 候选现在 3/3 标为 final_answer。主回复 5/6 最终准确否定错误结果且未补答案；另 1/6 因门禁无有效裁决回退。
- 助手语义复核：提交答案后的 3 次都只说“不对，再算算”，缺少配置要求的具体自检提示；追问后的 2 次最终回复满足要求，1 次回退。追问初稿 3/3 仍给出完整数数过程，两次经门禁与重试修正，另一次没有有效门禁裁决。不能宣称主生成行为已经修好。
- 语义复核独立保存为同目录 `.review.json`，含源报告校验和、逐样本结论，并明确 `human_confirmed=false`。未把用例标签改为 confirmed，未修改生产提示词或提交代码。
