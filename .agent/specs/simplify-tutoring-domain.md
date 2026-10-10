---
slug: simplify-tutoring-domain
created: 2026-10-10T00:54:21Z
status: draft
---

# simplify-tutoring-domain spec

## 做什么 / 为什么
将服务端答疑实现迁移到 `domain-tutoring.md` v3.1：只保护当前开放作业题的成果，原子知识可直接回答；过程题由已提交证据驱动最小下一步，不再用固定尝试次数解锁答案。同步把 Tutoring 从 Study 的领域目录中分离，消除旧答案状态与答疑许可中的跨领域职责。

## 验收标准
- [x] `TutorPermitPolicy` 位于 Tutoring Domain，只从当前 `ProblemRecord` 计算 `answer_protected`、`attempt_summary` 与 `active_subgoal`；不再接受任务、学习会话或任务标题，也不存在 `locked/unlocked/solved` 解锁语义。
- [x] 对 `open` 作业题，任何最终答案、完整解法、待填内容、选择项或代写候选都被出口检查拒绝；字词释义、翻译、发音、看图等 `knowledge_lookup` 可直接回答，即使当前 StudySession 带任务。
- [x] `ask_answer`、重复无进展和累计尝试均不会放开作业答案；只有已校验的完整思路/答案会将题目置为 `submitted`，且该状态不表示数学正确或已经掌握。
- [x] 每轮只推进当前 `active_subgoal`：有针对性证据才可保存下一个最小目标；无有效进展仍保持受保护，并允许模型改用更小目标、另一种表征或同构例子。
- [x] `TutoringProblem` 持久化为 `open | submitted | abandoned`、`active_subgoal`、必要计数与摘要；新 Alembic migration 移除旧 `solution_state`、`no_progress_streak`、`answer_requested`，并把既有数据安全映射为新状态。
- [x] 回任务提醒改为 Application 层基于 Study 的受权查询投影，不进入 `TutorPermit`；答疑不写 Study Aggregate。
- [x] 输入和输出均通过独立 `SafetyScreeningPort`（可注入 fake）裁决；主答疑模型的 `question_kind=safety` 最多只能收紧，不能作为唯一安全判定。
- [ ] 领域、工作流、迁移和架构测试覆盖上述边界；相关服务端测试全绿，`git diff --check` 通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  1. 新建 `app/contexts/tutoring/domain/`，迁移 `tutor_permit` 并改为证据驱动的 `ProblemStatus`/`TutorPermit`；删除 Study 内旧领域实现，更新全部 import 和架构目录断言。
  2. 调整 `tutor_turn.py`、`tutoring_workflow.py` 和只读工具：以 `answer_protected` 做不可绕过的作业成果检查，传递/保存 `active_subgoal` 与证据摘要；删除按次数解锁及以 `solution_state` 输出的 API 契约。
  3. 为 `tutoring_problems` 写新迁移并更新 ORM/物理设计文档；保留能安全迁移的历史计数，移除已废弃答案状态字段。
  4. 把回任务提醒抽成 Study Query 的 Application 投影；加入可替换的输入/输出安全筛查端口和默认实现，令危险输入或危险候选走固定安全话术。
  5. 改写并补齐 domain/workflow/架构测试，更新 `.agent/notes/113-evidence-driven-tutoring.md` 的实现记录。
- 测试计划：
  - 单元测试覆盖：原子知识直答、`open` 题的答案/完整过程拒绝、`ask_answer` 与任意次数卡住不解锁、有效子目标证据推进、`submitted` 不等于正确。
  - 工作流测试覆盖：持久化迁移后的状态和 `active_subgoal`、同题重放幂等、跨问题遗弃、回任务投影、输入/输出独立安全拦截。
  - 运行目标测试文件及受影响架构测试；最后运行服务端全量 pytest（或仓库约定的完整测试命令）和 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] Tutoring Domain 状态与许可策略迁移
- [x] 工作流、候选契约、工具和跨域提醒重构
- [x] 数据迁移、ORM 与物理设计同步
- [x] 独立安全筛查端口接入
- [x] 测试、架构断言与决策笔记更新
- [ ] 全量验证与 Gate 2 验收

## 备注
- 不实现通用数学验证器、离线评测或 A/B 平台；`submitted` 仅记录学生提交，不断言正确性。
- 历史 API 的 `solution_state` 是破坏性契约调整；本次以 v3.1 设计为准，调用方需改为消费 `problem_status`/`answer_protected`（如该字段对外暴露）。
