---
slug: tutor-turn-contract-hardening
created: 2026-10-13T01:23:34Z
status: done
---

# tutor-turn-contract-hardening spec

## 做什么 / 为什么
按代码复盘 `tutor-turn.v3` 后收紧契约：堵住两个保护漏洞（`clarify` 不过泄露检查；`relation=new` 换题后判官只看新题摘要），消除字段间的语义重叠（`act`/`depth`、`student_move`/`progress`/`evidence`、`content`/`follow_up_question`/`next_subgoal`），并删掉没有消费方的字段。契约升为 `tutor-turn.v4`。事实源 `docs/technical/domain-tutoring.md`。

## 验收标准
- [x] P0：题目受保护时，`clarify` 的 `content` 与 `candidates` 过答案标记检查和泄露判官；不受保护时行为不变。
- [x] P0：泄露判官（文字与图）拿到的 `problem` 包含本答疑会话最近的几道题（含被 `relation=new` 放弃的题）和孩子本轮的话；生产与离线评测共用同一个拼装函数。判官提示词升版。
- [x] P1：`depth` 只在 `act=answer` 时传给判官；`answer` + work + `reasoning` 记 shape flag `answer_on_reasoning`，不拒绝。
- [x] P1：`student_move != attempt` 时 `progress`、`evidence` 在解析时置空；`guide` + `request_hint` + `progress=submitted` 照常计提示。
- [x] P1：`tutoring.attempt_recorded` 只在 `substantive_attempts` 实际增加时发布。
- [x] P1：契约去掉 `follow_up_question`（模型返回也丢弃）；提示词写明 `next_subgoal` 就是 `content` 里所提问题的目标。
- [x] P1：`act=redirect` 不再追加系统回任务提醒。
- [x] P2：删掉 `history_ref`（含 `Verdict.history_ref`、工具箱 `authorized_refs`）、`check_authority`/`vet_candidate` 的 `has_work_input`、`ProblemAssessment.same_problem`；`Topic` 只含模型可写的两个值；`student_move` 进 `tutor.turn.result` 观测。
- [x] 提示词 `tutoring.turn.system.v8`、组件版本、摘要锁同步；`domain-tutoring.md`、`eval-offline.md` 等与代码同一 commit；旧 spec `tutor-turn-contract-v2` 归档。
- [x] 服务端全量测试全绿，`git diff --check` 通过。

## 实现计划（Gate 1：用户 2026-10-13 已确认三档一起做）
- 影响文件：
  - `app/application/workflows/tutor_turn.py`：契约 v4、`check_authority`（clarify 受保护时检查）、删 `history_ref`/`has_work_input`。
  - `app/application/workflows/tutor_loop.py`：`vet_candidate` 签名、clarify 判官文本含候选、`_fact_depth` 限 `answer`、`answer_on_reasoning` flag、`judge_problem_summary()`。
  - `app/application/workflows/tutor_shape.py`：去掉 `follow_up_question` 参数。
  - `app/application/workflows/tutor_tools.py`：删 `authorized_refs`。
  - `app/application/workflows/tutoring_workflow.py`：判官摘要、attempt 事实对齐、redirect 不提醒、删 follow_up 拼接、telemetry 带 `student_move`。
  - `app/contexts/tutoring/domain/tutor_permit.py`：删 `same_problem`。
  - `app/infrastructure/ai/prompts.py`、`components.py`、`tutor_turn_model.py`、`observability/telemetry.py`、`evals/runner.py`。
  - 测试：`tests/unit/tutoring/*`、`tests/application/study/test_tutoring_workflow_usecase.py`、`tests/support/fakes.py`、`tests/unit/evals/*`、提示词锁。
- 测试计划：每条 P0/P1 各一个先红后绿的用例；删除字段的旧测试改写或移除；全量 pytest。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] P0：clarify 泄露检查 + 判官多题摘要
- [x] P1：depth/act、student_move/progress、attempt 事实、follow_up、redirect
- [x] P2：删无用字段、Topic、telemetry
- [x] 提示词与组件升版、评测同步
- [x] 文档、note、归档

## 备注
- 不改 `abandoned` 的领域语义（不受保护）；只让判官看得到最近放弃的题。
- `depth` 保留（方案 A 依赖它），只收窄生效范围。
