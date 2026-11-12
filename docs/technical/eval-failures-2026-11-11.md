# 离线评测未通过清单（2026-11-11）

**后续处理：用户已要求将下表涉及的 7 份用例全部从维护 Dataset 删除，当前剩余 33 份。本报告保留删除前的历史结果，不作为当前用例清单或质量结论。执行器协议测试所需快照仅保留在 tests/fixtures，不参与离线评测。**

本次完成本地目录与加载器改造，未重新调用模型执行全量评测。以下来自最近已有的完整回放，**不是当前工作区的新运行结论**；没有修改用例标签、rubric 或阈值来消除失败。

## 结果口径与证据

- 40 份用例、77 个检查点：63 pass、11 fail、3 not_run，涉及 7 份未全部通过的用例。每点仅 1 次采样，未完成人工校准，不代表稳定通过率。
- 检查点级 error 为 0；逐项断言另有 9 个 error，集中在 3 个整页批改回退点，因同点有 fail 而聚合为 fail。
- 原运行代码记录 `b382150-dirty`，配置 `eval-grading-and-image-target-fix-draft`，配置 digest `25eb923528f8278dd6ca40e7f566605b5840de623372c17f9de0ff60b783aecb`；主模型 `qwen3.7-plus-2026-05-26`，时间为北京时间 2026-11-11。dirty 状态不能仅靠 commit 完整复现，须结合配置及原始日志。
- 本机原始证据：[汇总](../../duxue-server/var/evals/grading-v2-fixes-20261111/full-replay/summary.json)、[11 个失败的回复与逐项评分](../../duxue-server/var/evals/grading-v2-fixes-20261111/full-replay/failed-checkpoints.json)、[77 点索引](../../duxue-server/var/evals/grading-v2-fixes-20261111/full-replay/checkpoint-index.json)、[原分析与修复记录](../../duxue-server/var/evals/grading-v2-fixes-20261111/REPORT.md)。这些运行产物在 ignored `var/evals/`，不随 Git 分发。

## 全部失败检查点

以下用例 ID 记录删除前的文件。目录是主评测目的，同一对话中的判官复审不另复制到校准 Dataset。

| Dataset / 用例 | 检查点 | 用例描述与期望 | 未通过原因与待处理项 |
|---|---|---|---|
| teaching-correctness / `turn-protect-05`（已删除） | check-1 | 学生已提交方程答案 x=4，应独立核验并准确反馈。 | 回复称不能确认对错并要求重新提供原题，属于过度保护。需检查题目上下文和模型遵循，不能用关键词强制确认。 |
| orchestration-tools / `turn-97103aaf-06`（已删除） | check-1 | 学生确认要读上一轮选定的第四句，应为该句提供发音。 | 实际读成 Return to Bali。原排查发现图片历史隔离会丢失助手的确认线索；需保留明确的目标引用，直接恢复全部历史会带回旧图错误结论。 |
| teaching-correctness / `turn-rubric-00`（已删除） | check-1 | 学生错误移项得到 2x=14、x=7，应指出具体错误并给下一步。 | 新回复虽未再肯定错误结论，但仅追问推导，没有定位移项错误；教学反馈不满足要求。 |
| judge-calibration / `unknown-length`（已删除） | check-1 | 判断候选是否泄露待求长度。 | 与 known-length 的被测输入相同且无图，差别只在不传给被测判官的 reference_problem，却期待相反标签。**用例证据不足**，需补原图或经确认的可见前提，不能注入 gold 或直接改成通过。 |
| orchestration-tools / `knowledge-switch-and-return`（已删除） | check-3 | 暂停铅笔题，直接讲解植物与动物细胞区别并提供对比图。 | 回复坚持先完成铅笔题，未讲解细胞，也无配图。任务切换及配图协议遵循失败，需进一步定位，暂无验证过的最小修复。 |
| guidance-logic / `answer-feedback-conversation`（已删除） | submitted-answer-feedback | 肯定列式正确、指出结果错误，给孩子可操作的自检提示。 | 回复仅说“4+5不等于8，再算算看”，未明确肯定列式且提示泛泛。quality 给 4 分，case_requirements 判失败；**标准适用需人工校准**，暂保留失败。此前曾通过，不能单凭一次输出认定代码回归。 |
| teaching-correctness / `new-image-review-conversation`（已删除） | recheck-1 | 根据新上传照片逐题核验，指出实际错误。 | 候选 JSON 截断后回退；原始候选还把正确的 60−15=45 判错。输出预算与数学可靠性均有问题。 |
| 同上 | recheck-2 | 用户纠正“新图”后，应核验第二张照片。 | 选图已正确，但候选 JSON 仍截断并回退；选图子检查通过不等于完整用例通过。 |
| 同上 | recheck-3 | 再次上传照片后核验当前页，不能漏掉 34−(28−13) 最后写成 17 的错误。 | 选图正确，候选仍存在数学误判、输出截断，最终回退。 |
| 同上 | audit-attempt-1-1 | 对固定历史候选重新审核，应拦截无依据的批改结论。 | 期望 premature_conclusion，生产判官实际返回 leaks=false / reason=none，未拦截。需视觉核验和判官校准。 |
| 同上 | audit-attempt-3-0 | 审核固定候选对整页作出的错误核验结论。 | 同样期望 premature_conclusion，但生产判官放行；没有通过调整离线评分来掩盖生产判官问题。 |

## 未执行与执行异常

`knowledge-switch-and-return` 在 check-3 失败后中止，以下 3 点为 **not_run，不能算通过或独立失败**：

| 检查点 | 待验证内容 | 未执行原因 |
|---|---|---|
| check-4 | 返回原铅笔题，给予提示但不透露最终结果。 | 前序 check-3 失败，连续会话中止。 |
| check-5 | 学生算出总数 24 后，推进到减去送出的数量。 | 同上。 |
| check-6 | 学生提交剩余 19 支，独立核验并反馈。 | 同上。 |

9 个断言 error 分别是 `new-image-review-conversation/recheck-1、2、3` 的 `exit_gate_leaks_eq`、`exit_gate_reason_eq`、`exit_gate_answer_protected_eq`：生成阶段回退，缺少有效生产门禁观测。它们不是 9 份额外失败用例，也不能当作门禁判定已通过。

## 后续已有专项结果

提高输出预算至 6000 token、超时至 60 秒的[独立专项](../../duxue-server/var/evals/grading-v2-fixes-20261111/budget-verification.json)仍为 1 pass / 5 fail：7 次生成均返回完整 JSON，但前两个生成点仍候选无效回退，第三点交付内容存在数学误判；至少一个候选的 `image_review.questions[0].basis` 超过 300 字协议上限。两个固定候选复审仍失败。这个专项不能替换上述全量统计，也不证明增大预算已修复整页批改。

## 本次本地改造验证

5 个目的目录共 40 份 JSON，内容与迁移前逐文件 SHA-256 一致，未修改历史来源说明。加载器按 `type` 选择执行方式，支持目的目录内混合类型；新增混合目录覆盖、非法类型和缺失路径测试。评测相关单元测试 172 项通过，`python -m evals validate` 通过（16 单轮、5 多轮、16 判官、3 真实对话）。这证明目录和加载逻辑可用，不等于上述模型质量问题已修复。
