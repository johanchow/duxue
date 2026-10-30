# 真实对话回放配置草案：等待用户确认

日期：2026-10-30。

- 用户纠正：一例一文件指完整评测场景，不能把真实多轮对话扁平化为多条孤立 `problem/reply`。用户明确要求先清理旧格式、写出新用例，确认后才能适配执行器和执行。
- 本阶段撤掉 answer-feedback-v1 的 5 条主流程和 11 条门禁拆分用例；历史 seed 及此前 15 条首图判官用例保留。
- 唯一待审用例：[answer-feedback-conversation.json](../../duxue-server/evals/data/conversation_replay/answer-feedback-conversation.json)。内容直接来自 Langfuse 两条已核对的 trace，保留有据可查的 5 轮/10 条原始消息，不纠正 ASR 或改写数学题人名；明确 coverage=observed_window，不宣称是全线程导出。
- 3 个实际模型候选、原 gate 输入及判定、重试反馈放在 attempts；只有真实展示的回复进入 messages，包括最终兜底消息。5 个检查点引用消息或候选，原始 observed_verdict 与新的 expect 分开。合成变体没有冒充真实消息。
- 格式仍待用户确认：未修改执行器、schema、正式规范或原有测试，也未运行模型评测、CLI 校验或测试。当前草案尚未纳入执行器支持范围；不能将之前的 719 passed 当成本次改动的验证结果。
- 用户确认后，再补通用 fixed_history 回放适配及测试，按各检查点之前的原始消息重放，不把本次新生成的回复回灌为真实历史。
- 用户追问正确期望的位置后，仅补充 checks.expect：两轮主流程增加 reference_response、exit_gate 与明确判定要求；原始候选仍按是否实际给出新结果判定。messages、attempts 和 observed_verdict 不改写，参考回复不作为逐字匹配答案。本阶段仍未运行评测或测试。
- 用户要求显式标记期望正文，已将两处 reference_response 更名为 checks[].expect.response.message；门禁期望仍在 exit_gate，判定要求在 criteria，原始对话保持不变。仍等待用户确认后执行。
