---
slug: tutoring-latency-optimization
status: draft
created: 2026-11-20T13:55:54Z
author: johan
---

# Tutoring Workflow 耗时优化（第一、二批高收益零降质改动）

## 验收标准

1. **归零新题首轮无效同步等待**：`TutoringWorkflow` 中 `SOLVE_FIRST_TURN_BUDGET_SECONDS` 默认值由 `2.5` 调整为 `0`（仍支持显式环境变量或构造参数覆盖）；命中 `ready` 档案仍直接复用，`pending` 时零阻塞进入首轮苏格拉底审题引导。
2. **并行执行独立出口审核（由 Admin 库表 `workflows/tutoring-vet.json` 声明式 DAG 驱动）**：
   - 升级 `workflows/tutoring-vet.json` 与 `workflows/tutoring.json`（经 `subworkflows.py` + `scripts/upgrade_workflow_nodes.py` 导入 Admin 库表）：将 `tutoring-vet.math_consistency` 迁入 `tutoring-vet`，与 `tutoring-vet.text_leak`、`tutoring-vet.visual_leak` 并列从 `tutoring-vet.authority` 扇出（`needs_math_review` / `needs_text_review` / `needs_visual_review`），并无条件汇聚到 `tutoring-vet.complete`。
   - 先在 `tutoring-vet.authority` 完成本地确定性校验（教学权限 + 数学证据账本 `ledger.validate()`）；不通过直接走 `authority_denied` 短路至 `complete`，0 次 Judge LLM 请求。
   - 当命中 ≥ 2 条审核边时，由 `runtime.execute_workflow()` 原生并发 fan-out/fan-in 驱动执行（隔离各分支 `Recorder` 子轨迹并按序合并），在 `tutoring-vet.complete` 严格按既有优先级裁决：`math_check_failed` / `math_inconsistent` > `leak_check_failed` / `leak_detected` > `visual_not_helpful` / `visual_leak_detected` / `visual_leak_check_failed`。
   - 保持 `WORKFLOW_BINDINGS` 与既有已发布快照的 `compatibility` 指纹逐字节不变，旧快照继续按旧拓扑向后兼容运行。
3. **Admin 草稿校验/发布前 Judge 必填输出预检**：
   - `compile_bundle()` 静态门禁：启用 `tutoring.math` 时，`gates/tutoring.leak-judge.json` 的 prompt 模板与 `provider_output_schema` 必须显式包含 `math_consistent`；正文保护核心字段（`answer_protected`、`new_final_answer`、`complete_solution`、`choice_verdict`、`incorrect_confirmation`、`premature_conclusion`）必须在 `provider_output_schema` 中完整声明。
   - 新增可复用的 Judge 契约探针 `app/agent_specs/judge_preflight.py` 并在 `/internal/agent-admin/validate` 支持可选 `probe_judges: bool = False`，分别用数学审核样本与正文审核样本验证必填输出，提前拦截类似 R12 缺失 `math_consistent` 的配置漂移。
4. **取消首轮无条件预加载 `widget_guidelines`**：
   - `call_tutor_model()` 不再因 `visual_delivery_enabled()` 首轮无条件注入 ~5.3KB `widget_guidelines`；保留按需工具调用，以及 `visual_schema` 失败、未加载规范生成 SVG、`missing_visual_redraw` 时的自动补加载兜底。
5. **配图泄露重画（`visual_redraw`）收窄审核范围**：
   - 当正文、题面、学生作答与授权上下文完全一致且仅重画 `visual` 时，复用已过审的正文裁决（不再重复跑纯文本答案泄露重试，但仍校验 `visual_schema`、`visual_leak` 与（开启数学核验时的）图文数学一致性）；若模型试图改写已过审正文则继续拒绝重画。
6. **测试与静态检查全绿**：
   - 新增/更新针对并行审核、固定双失败优先级、0s 首轮预算、Judge 编译/探针预检、按需 `widget_guidelines` 与重画复用正文审的红→绿单测；
   - 服务端相关单测全绿、修改文件 Ruff 通过。

## 实现计划

### 影响文件
- `duxue-server/app/application/workflows/tutoring_workflow.py`：`SOLVE_FIRST_TURN_BUDGET_SECONDS` 默认值改为 `"0"`。
- `duxue-server/app/application/workflows/tutor_loop.py`：
  - 先做本地 `authority` + 数学账本校验，再并行执行 `math_consistency` / `text_leak` / `visual_leak`；
  - 取消 `call_tutor_model` 首轮无条件预加载 `widget_guidelines`；
  - `visual_redraw` 正文未变时收窄审核范围（复用已过审正文裁决，仅复核新图与图文一致性）。
- `duxue-server/app/agent_specs/admin_bundle.py`：强化 `tutoring.leak-judge` 必填字段与 `math_consistent` 编译期门禁。
- `duxue-server/app/agent_specs/judge_preflight.py`（新增）：数学审核 + 正文审核双样本契约探针。
- `duxue-server/app/api/v1/agent_admin.py`：`/validate` 支持可选 `probe_judges` 参数。
- `duxue-server/tests/unit/tutoring/test_parallel_vetting.py`（新增）：并行审核、双失败优先级、0s 首轮预算、重画范围收窄、按需 `widget_guidelines` 回归测试。
- `duxue-server/tests/unit/agent_specs/test_judge_preflight.py`（新增）：静态编译门禁 + Judge 探针预检回归测试。
- `duxue-server/tests/unit/agent_specs/test_subworkflows.py`：更新并行审核后的轨迹与优先级断言。

## 完成度清单

- [x] 1. 归零 `SOLVE_FIRST_TURN_BUDGET_SECONDS` 默认等待并补单测
- [x] 2. `tutor_loop.py` 实现本地前置短路 + `math_consistency` / `text_leak` / `visual_leak` 线程安全并行审核与固定失败优先级
- [x] 3. `tutor_loop.py` 取消首轮无条件预加载 `widget_guidelines` 并收窄 `visual_redraw` 重审范围
- [x] 4. `admin_bundle.py` 强化 Judge 必填字段静态门禁 + 新增 `judge_preflight.py` 与 `/validate` 可选探针
- [x] 5. 删除散装 `tests/fixtures/agent_specs/workflows/`，服务端与 Admin 单测统一收敛至 `tests/fixtures/admin-release.json`
- [x] 6. 通过 `upgrade_workflow_nodes.py` + `importConfigUpgrade` 将并行 `tutoring-vet` 拓扑导入 `duxue-admin-test` 工作草稿（`da210b2f-d24e-40cf-9e4f-db60ef3c99e5` revision 12，digest `e9590b283f8788ed98dc2c2cd1af49d41e780f4100eca114d1b126c2aee47e34`，不发布）并回读核验
- [x] 7. 补全并跑通全部相关单元测试、Admin 单测 + typecheck 与 Ruff 检查
