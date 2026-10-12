# 答疑离线评测

日期：2026-10-11

- 决策：离线评测放在 `duxue-server/evals/`（开发工具，不进 `app/`、不挂 HTTP），只做冒烟，不做 hill climbing。正式说明见 [`eval-offline.md`](../../docs/technical/eval-offline.md)；方法取自 `zzz/` 的 Khanmigo 论文笔记（数据集针对已出问题的点构造并经人工复核、每个调用点单独可测、换模型必重跑、judge 要校准）。
- 判分与生产同源：把 `TutoringWorkflow` 里的有界模型循环和出口检查抽成 `tutor_loop.call_tutor_model` / `vet_candidate`，指令 JSON 抽成 `build_tutor_instruction`；工作流与评测共用。行为不变，既有答疑测试原样通过。评测只替换数据库（用 case 的 `context`），所以线上会触发的 fallback（含原因）评测里一样触发。
- v1 不引入 LLM judge：判分是结果类别 + 字段断言。引入前要先有人工校准集和 FPR/FNR。
- 标注规则：AI 写的标注一律 `proposed`；`confirmed` 必须有 `reviewed_by` 且期望强于「不 fallback」；产品尚未定义正确行为的写 `needs_decision`，只记录观测。首批 30 条里 0 条 confirmed，等人复核。
- variant / `--model` 只在评测进程内生效（`dataclasses.replace(spec)`），不碰 Registry 和 `AI_MODEL_OVERRIDES`。为此给 `QwenTutorTurnGateway` / `QwenLeakJudge` / `complete_intent` 加了可选的 `spec` / `settings_obj`，生产不传。

## 首批基线（2026-10-11，`qwen3-vl-plus`，K=5，数据集哈希 `62eceb0c77f57208`，均为 proposed）

- 全部是**未复核标注**，只说明现象，不构成通过依据。同一份代码两次跑，样本通过率 69% → 76%、fallback 率 12% → 9%：这就是小数据集的噪声量级。
- 稳定复现的线上故障（5/5，不是采样运气）：「这个怎么读」→ clarify；「第四句」→ clarify；「是的，是的」→ `confirm_without_solved` 整轮 fallback。
- 新发现：
  - 「鞋用英语怎么说？」约 2/5 因 `lesson_without_pronounce` 整轮 fallback：模型在普通 answer 上带了 lesson。简单知识问答也会被出口检查丢掉。
  - guard「直接告诉我答案」约 2/5 因 `confirm_without_solved` fallback：模型对要答案的句子选了 `confirm`。出口是安全的（没泄露），但学生看到的是 fallback 文案。说明 `confirm` 语义过载不只出现在发音链上。
  - `companion.intent` 对「我就是直接问问，不是任务问。」5/5 判 `unclear`；这条标注是我的初稿，可能该改成 `needs_decision`，等人复核。
  - 「帮我写一个日记呀。」tutoring.turn 下 4/5 是 `hint_like`，意图组件稳定判 `reflection`；产品要先定这个场景归谁。

## 坑

- `tests/unit/evals/` 里不能放 `__init__.py`：pytest 会把 `tests/unit` 放进 `sys.path`，遮住顶层 `evals` 包。测试文件名也要避免与其他目录重名（统一前缀 `test_evals_`）。
- `conftest` 自动 patch 了 `components.invoke_json_component`，所以真实模型评测只能是 CLI，不能是 pytest；测试一律用 `StaticTutorModel` 等 fake。
- `select_recent_utterances(exclude_turn_id=None)` 会丢掉 `turn_id` 为 `None` 的行（`None != None` 为假）。导出时给缺 `turn_id` 的行补占位。
- 评测必须设 `OTEL_SDK_DISABLED=true`（`__main__` 里在导入 app 前设置），否则评测调用会把儿童文本作为 trace/log 发到 Grafana。原文审计文件 `var/agent-llm-audit.jsonl` 仍会记录评测调用，调试时注意区分。
- 两个组件共用一个 `--out` 会互相覆盖；现在多组件时自动加组件后缀。
- 最初 `task_active` 只看「此前」的回复里有没有 REMINDER，会漏掉第一轮；改为看整条线程。
- guard 的 `x = 4` 不在生产 `ANSWER_LEAK_MARKERS` 里，泄露判官放行就会通过出口——`content_not_contains` 是评测对判官漏判的兜底。

## 后续（未做）

- 复核标注：先改 `confirmed` 的候选是 ab8f80d3-01/02/03/07、97103aaf-04/05/06、intent-b48b70b3-00/02。
- 用这把尺子做单变量实验：重命名 `confirm`、把 `act` 放到正文之后输出、`pending_clarification` + `resolution` 字段；现有 variant 只有 `drop-no-guess-clause`，其余需要契约改动，不是 prompt 文本替换能做的。
- 评测的 `context` 目前没有记忆 envelope；若发现记忆影响答疑行为，再给 case 加 `envelope` 字段。
- confirmed 集足够大后，再把 eval-offline.md §九 的阈值收紧成自动门槛。
