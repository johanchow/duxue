---
slug: leak-gate-deterministic-fact
created: 2026-10-13T02:16:00Z
status: done
---

# leak-gate-deterministic-fact spec

## 做什么 / 为什么
泄露判官对"空格里的单个事实"判断不稳定（note 121：depth-04 曾 0/5 全回退，v2 靠把 `depth` 告诉判官才放行，仍是概率性的）。改为：单个事实由代码确定性放行，不再问判官；判官只按严格标准审其余回复；被判泄露后重试一次改为 `guide`，把误拦从"兜底话术"变成"最小提示"。保护不放松：标签之外还要过代码规则，答案标记检查始终照跑，判官出错仍 fail-closed。

## 验收标准
- [x] 事实闸门 `fact_gate()`：`act=answer`、（`depth` 为 atomic/recall 或 `topic=atomic_lookup`）、`content` 不超过 40 字，且不含数字、算式符号、单独的选项字母、对错判断、推理连接词时放行，跳过文字判官；任一不满足按严格标准交判官。
- [x] 判官不再接收 `depth`：`LeakJudgePort.leaks` 去掉 `depth`，`tutoring.leak-judge@v4` 提示词去掉放行单个事实的段落。
- [x] 闸门放行时，带图的回复仍单独过图判官；答案标记检查不受闸门影响。
- [x] 文字被判泄露（`answer_marker`、`leak_detected`）后，带 `repair_error`（"泄露："开头）重试一次；重试结果重新走完整出口检查，仍不过才回退。判官失败（`leak_check_failed`）不重试。生产与离线评测共用 `run_tutor_turn()`。
- [x] `model_fallback` 只按最终结果记录；重试与闸门结果进观测。
- [x] 提示词 `tutoring.turn.system.v9` 说明"泄露："重试要改用 `guide`；组件版本、摘要锁同步。
- [x] `domain-tutoring.md`、`infra-ai-components.md`、`eval-offline.md`（如涉及）同步；note 123。
- [x] 服务端全量测试全绿，`git diff --check` 通过。

## 实现计划（Gate 1：用户 2026-10-13 已确认，阈值改为 40 字）
- 影响文件：`tutor_loop.py`（闸门、`run_tutor_turn`、`call_tutor_model` 支持初始 `repair_error`、fallback 记录上移）、`tutor_turn.py`（`LeakJudgePort`）、`tutoring_workflow.py`、`evals/runner.py`、`tutor_turn_model.py`、`prompts.py`、`components.py`、`telemetry.py`；测试 `test_visual_vetting.py`、工作流用例、`fakes.py`、提示词锁。
- 测试计划：闸门每条规则一正一反；depth-05/06 型的谎报（数字、对错）不放行；重试成功展示提示、重试仍泄露回退、判官失败不重试；评测路径同源。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 事实闸门 + 判官去 depth
- [x] 泄露后重试一次（共用 `run_tutor_turn`）
- [x] 提示词与组件升版
- [x] 文档、note、归档

## 备注
- 闸门规则宁可误判成"不是单个事实"（多一次判官调用），不可误放。
