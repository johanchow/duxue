# 112 答疑改为「LLM 驱动 + 代码守出口」

## 背景

线上日志显示孩子问「图片内容是哪个 App 拍的」被判成 `problem`，只得到反问。根因是固定分类（意图、题型、L1–L4）加五次串行调用：分类缺口直接变成教学行为错误。`failed_attempts` 其实是 Ward 消息条数，不是真实的有进展尝试。

## 决策

- 唯一红线：作业成果不被代替完成，用 `SolutionState`（locked / unlocked / solved）表达。其余全是教学做法，交给模型。
- `HintingPolicy` 改为 `TutorPermitPolicy`：`permit()` 在调用前算许可，`advance()` 在提交时推进 `ProblemRecord`。本轮表现下一轮才生效。
- 解锁条件：连续 2 次无进展；尝试数达到 N（默认 3）；要答案且至少有 1 次尝试。仅 `ask_answer` 不解锁。
- 模型返回统一契约 `TutorTurnCandidate`（act、question_kind 等自述标签）；代码只用标签收紧，不放松。
- 出口三道检查每轮必经：结构（重试一次）、越权与一致性、泄露（独立小调用，fail-closed）。失败统一回退固定话术，不写 Fact。
- 发音并入同一流程（`act=pronounce`），UI 的 `tutoring_intent` 只是期望动作提示。
- 只读工具：每轮 ≤3 次工具、≤4 次主模型调用。

## 待产品确认的参数

N=3、连续无进展=2、工具上限 3、模型调用上限 4。

## 风险

泄露检查是概率性的；自述标签可能错；`is_assignment_content` 在有 open 题且 same_problem 时由代码强制。

## 否决的方案

- 代码固定 workflow 加分类调用：长尾场景靠枚举补不完。
- 把 L1–L4 换成更多等级：问题在抽象本身，不在级数。
- 用提示词承担红线：不可验证。

## 状态

设计见 `docs/technical/domain-study.md` v3.0。代码已按迁移 1 到 4 步落地（`tutor_turn.py`、`tutor_permit.py`、`tutoring_workflow.py`、`tutor_turn_model.py`）；工具循环已做（`tutor_tools.py`：get_task_context、get_attempt_summary、lookup_history；预算 3 次工具 / 4 次主调用）；inspect_image 因缺图像裁剪依赖未做。测试全绿，除已知的 `test_e2e` 一条（与本改动无关）。`design-server.md` 里的 `hint_level` 在实现时同步。

## 实现时的坑

- 发音和澄清是只读的，所以 `StudySession`/`TutoringSession` 要等到确定要写时才打开（`_ensure_tutor`），否则发音会凭空开出会话和事实。
- 同一 `turn_id` 重放不重复计数，靠 `tutoring_problems.last_turn_id`。
- 旧的 `validate_tutoring_input` 关键词会在到模型之前拦掉“直接告诉我答案”，使 ask_answer 永远到不了策略，已不再调用。
- `tutoring_messages.hint_level` 列保留但新行不写；API 与事件改用 `hint_index`。`design-server.md` 与 `api/v1/study.py` 的旧路径仍引用该列，待同步。
