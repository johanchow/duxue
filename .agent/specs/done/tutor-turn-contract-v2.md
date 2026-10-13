---
slug: tutor-turn-contract-v2
created: 2026-10-11T12:05:50Z
status: done
---

# tutor-turn-contract-v2 spec

## 做什么 / 为什么
把答疑模型契约 `tutor-turn.v1`（14 个扁平字段、多处自述信号重叠）收敛为 v2：顶层只有 `act` + `content`，其余按用途放进可选子对象。出口检查分成「安全拒绝」与「元数据规范化」两类，后者不再整轮回退。

动机：note 114 / 115 / 119 反复出现同一故障——与安全无关的字段不一致（`confirm` 无 `solved`、`lesson`/`candidates` 与 act 不匹配、错位 `question_kind`）把本可展示的回答换成固定兜底话术。事实源见 `docs/technical/domain-tutoring.md`，本 spec 完成后同步其契约章节与 `eval-offline.md`。

## 目标契约（草案）
```json
{
  "act": "answer | guide | chat | clarify | redirect | pronounce | safety",
  "content": "...",
  "work":      { "relation": "none | same | new",
                 "student_move": "attempt | request_hint | request_answer | other",
                 "progress": "none | some | submitted",
                 "evidence": "...", "next_subgoal": "..." },
  "clarify":   { "candidates": [] },
  "pronounce": { "lesson": {} },
  "follow_up_question": "...", "history_ref": "..."
}
```
- 必填只有 `act`、`content`；子对象全部可省略；不适用于当前 act 的子对象一律丢弃，不拒绝。
- 去掉：`confirm`、`reveals_solution`、`is_assignment_content`、`same_problem`、`question_kind`、`student_turn_kind`（被 `work` 和 `act` 取代）。`probe/hint/example` 合并为 `guide`。
- `progress=submitted` 只表示孩子提交了完整思路/答案，不表示正确（与 `ProblemStatus.submitted` 对齐）。
- `answer`/`guide` 必须有 `work.relation`，缺失或非法不猜，走一次结构重试；其它 act 缺 `work` 按 `none`。新增 `chat` act，用来保住「知识问答记好奇心、闲聊不记」的区分。
- `act=safety` 只能收紧：`SafetyScreeningPort` 的输入/输出裁决仍是最终依据，筛查器拦截时模型无法用其它 act 绕过。

## 验收标准
- [x] 出口检查分两类：**拒绝类**（`reveals_protected_work_product`、`answer_marker`、泄露判官、安全筛查、`pronounce` 缺 `lesson`）保持行为不变；**规范化类**（子对象与 act 不匹配、`next_subgoal` 非作业、`submitted` 无证据）只丢弃/降级，不触发 fallback。
- [x] `confirm_without_solved`、`lesson_without_pronounce`、`candidates_without_clarify`、`subgoal_without_work_product` 四个 reason 不再存在；对应输入有测试证明得到正常回答。
- [x] 作业保护不变：开放题上 `act=answer`（或内容含答案标记/被判泄露）仍被拒；`work` 缺失在有开放题时按 `same` 保护；`ask_answer`/卡住不解锁。
- [x] `submitted` 不会在文案或事实里被当作"正确"；提示词不再出现"确认正确"。
- [x] 计数语义不变：`HINT_ACTS` 改为 `guide` 后，`hints_given`、`tutoring.hint_given`、`curiosity_observed`、`hint_index` 行为与旧 `probe/hint/example` 一致；`act` 对外字段变化已确认无前端消费（`duxue-app` 未读取 `act`）。
- [x] 离线评测：`evals/outcome.py` 的 outcome 映射、数据集与判分改到 v2，K=5 跑 16 个 proposed 用例，通过率不低于 119 后的 70/80，且 fallback 原因里不再有规范化类 reason；结果与局限记入 note。
- [x] 提示词升版（`tutoring.turn.system.v3`、组件版本、摘要锁同步），`domain-tutoring.md`、`eval-offline.md`、`infra-ai-components.md` 与代码同一 commit。
- [x] 服务端相关测试全绿，`git diff --check` 通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 已查明的下游依赖（act 取值）：
  - `contexts/tutoring/domain/tutor_permit.py`：`HINT_ACTS = {probe,hint,example}` 用于 `hints_given`；`ProblemAssessment` 带 `act`、`student_turn_kind`、`progress`、`same_problem`。
  - `application/workflows/tutoring_workflow.py`：`question_kind==safety`、`knowledge_lookup`（curiosity 事实）、`student_turn_kind==attempt`（attempt 事实）、`same_problem`（换题/重放）、`act in HINT_ACTS`、`next_interaction.act`。
  - `application/workflows/tutor_loop.py:117`、`pronunciation_guidance.py`：`clarify` + `lesson`。
  - `evals/outcome.py`、`evals/schema.py`：act→outcome 映射（`hint_like` 合并 3 个 act、`confirm` 独立 outcome）。
  - 测试大量使用 `tutor_raw(act=..., question_kind=..., ...)`（`tests/support/fakes.py` 等），需整体迁移。
- 步骤（每步配测试，小步提交）：
  1. **A（先于契约改动）**：在 v1 上把 `check_authority` 的规范化类规则改成降级而非拒绝，补"不再回退"的测试；这一步可单独合并。
  2. 新契约模型 `TutorTurnCandidate` v2：子对象独立校验、不适用即丢弃；删除 `normalize_pronounce_shape` 的错位修复。
  3. 适配 `check_authority`、`TutorPermitPolicy`（`guide` 计提示，`submitted` 取代 `solved`）、`tutoring_workflow`（`act=safety`、`work.relation`、curiosity 判定改为 `act==answer` 且 `work.relation==none`）。
  4. 提示词 v3、组件版本、摘要锁；评测 outcome/数据集/判分迁移。
  5. 文档同步 + note 120；跑评测对照。
- 测试计划：
  - 单元：每个丢弃/降级规则一个"回答照常展示"的测试；每个拒绝规则一个"仍被拒"的测试；`work` 缺失 fail-closed；`act=safety` 与筛查器的"只能收紧"。
  - 工作流：hint 计数、attempt/curiosity 事实、换题与重放幂等、发音/澄清只读不写库。
  - 评测：`tests/unit/evals/*` 与离线 K=5 对照（局限：样本小，代码与提示词需分两次测以便归因）。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 步骤 1：规范化类规则降级 + 测试（与 2 合并实现）
- [x] 步骤 2：v2 候选模型
- [x] 步骤 3：权限策略与工作流适配
- [x] 步骤 4：提示词 v3 与评测迁移
- [x] 步骤 5：文档同步、note、评测对照

## 备注
- 步骤 1 可独立发布，风险最低，建议先做；步骤 2–5 是破坏性契约变更，需 Gate 1 确认后再动。
- 已定：`guide` 不保留 probe/hint/example 区分；`redirect` 保留，与 `chat` 并列。
- 一次做完 1–5（项目未上线）。
- 后续：契约已演进到 `tutor-turn.v3`（`turn` 判别联合 + `depth`，见 note 121）与 `tutor-turn.v4`（见 `done/tutor-turn-contract-hardening.md`、note 122）；本文件的目标契约草案只作历史。
