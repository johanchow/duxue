---
slug: stage1-thinking-and-math-upgrade
created: 2026-11-15T10:25:36Z
status: implementing
---

# Stage 1：API 受控 Thinking + 高中 MathExecutor 扩界与解耦

## 做什么 / 为什么

为支撑 K12 高中高考深度理科与伴学场景（及后续 `omni-edu-v1` 210 题 A/B/C 三组对照实验），在保持现有 Admin 发布包兼容性与生产隔离边界的前提下：
1. 打通 API 受控思考链（`enable_thinking` + `thinking_budget`），支持 DashScope 流式思考分片聚合、思维链隐藏（不向 Ward 展示、不写入生产 Trace 正文）与推理 Token 观测；
2. 升级 `math_executor` 受限 SymPy 计算内核，覆盖高中复数、分数/符号指数、多元方程组、含参方程、单变量不等式（组）、任意底对数、反三角、排列组合与平面/空间向量运算，并增加纯四则快路；
3. 解耦数学核验状态与答案泄露门禁（分离 `math_inconsistent` / `math_check_failed` 与 `leak_detected` / `leak_check_failed`，不缓存临时 `unavailable`/`timeout`，为本地评测提供显式受管子进程模式与真实计算 preflight）；
4. 贯通 `Ward.grade_stage` 到答疑上下文，扩展快照升级脚本与本地评测汇总指标（P50/P90 延迟、泄题重试率与回退原因分布）。

Gate 1：用户已明确指令先按方案中的 Stage 1 进行代码实现，本轮不执行真实付费模型评测。

## 验收标准

- [x] `ModelDefinition`、`ComponentSpec` 与 Admin 编译/UI 支持可选 `enable_thinking: bool = False`、`thinking_budget: int | None`（仅 `enable_thinking=True` 时允许设置预算）；既有快照 `compatibility` 指纹保持不变。
- [x] `complete_json_chat` 在 `enable_thinking=False` 保持原非流式请求不变；在 `enable_thinking=True` 自动启用 `stream=True` + `stream_options={"include_usage": True}` 聚合 `delta.content`，严格隔离 `reasoning_content`（不入学生可见回复、不入 Trace 文本），记录 `tokens_reasoning` 与配置标记，兼容确定性 JSON 围栏剥离；`evals.local.solve` 同源复用且满足 `test_no_direct_model_calls`。
- [x] `math_executor` 支持复数单位 `I`、有理分数幂与受限符号指数、多元方程组与含参方程求解、单变量实数不等式（组）求解、`ln`/`log(x, base)`/`cbrt`/`root`/`cot`/`asin`/`acos`/`atan`、`factorial`/`binomial`/`gcd`/`lcm` 及 2D/3D 向量 `dot`/`norm`/`cross`；全部恶意代码/超限指数/超限阶乘输入继续拒绝。
- [x] 数学审核失败与不可用分别映射为 `math_inconsistent` / `math_check_failed`，不冒充 `leak_detected` / `leak_check_failed`；`MathVerification` 不缓存临时 `unavailable`/`timeout`/`resource_limit`；发音/安全/重定向无数学记录轮次不触发冗余 `check_math`。
- [x] 生产环境强制保持独立容器 Unix socket 模式；非生产本地评测支持显式 `MATH_ENGINE_MODE=subprocess` 受管隔离子进程模式，并在 `evals/live.py::preflight()` 执行真实算式预检。
- [x] `TutoringWorkflow` 将 `Ward.grade_stage` 注入受权 `ContextEnvelope.actor`；`scripts/upgrade_math_bundle.py` 支持生成 Stage 1 对照快照；`evals/local/report.py` 汇总输出延迟分位数（含 P90）与 `leak_retried` / `fallback` 统计。
- [x] 新增红绿单元测试覆盖 Thinking 流式聚合与脱敏、Admin 快照兼容、高中数学引擎全部新能力与安全边界、数学门禁解耦与本地评测汇总；服务端 1147 项测试、管理台 52 项测试、TypeScript 构建与修改文件 Ruff 检查全绿，未运行付费模型评测。

## 实现计划

- 影响文件：
  - `duxue-server/app/agent_specs/definitions.py`、`duxue-server/app/agent_specs/admin_bundle.py`、`duxue-server/app/agent_specs/catalog.py`
  - `duxue-server/app/infrastructure/ai/components.py`、`duxue-server/app/infrastructure/observability/telemetry.py`
  - `duxue-server/math_executor/arithmetic.py`、`duxue-server/math_executor/engine.py`、`duxue-server/app/infrastructure/math_engine/adapter.py`、`duxue-server/app/bootstrap/math_engine.py`
  - `duxue-server/app/application/workflows/math_verification.py`、`duxue-server/app/application/workflows/tutor_loop.py`、`duxue-server/app/application/workflows/tutor_turn.py`
  - `duxue-server/app/application/queries/context_builder.py`、`duxue-server/app/application/workflows/tutoring_workflow.py`
  - `duxue-server/scripts/upgrade_math_bundle.py`、`duxue-server/evals/live.py`、`duxue-server/evals/runner.py`、`duxue-server/evals/local/solve.py`、`duxue-server/evals/local/report.py`、`duxue-server/evals/local/__main__.py`
  - `duxue-admin/src/components/studio.tsx`、`duxue-admin/src/components/inventory.tsx`
  - `docs/technical/tutoring-math.md`、`docs/technical/design-agent.md`
- 测试计划：
  - `duxue-server/tests/unit/ai/test_components.py`、`test_no_direct_model_calls.py`、`test_prompt_lock.py`
  - `duxue-server/tests/unit/agent_specs/test_single_source.py`
  - `duxue-server/tests/unit/math_engine/test_engine.py`、`test_execution.py`、`test_workflow.py`
  - `duxue-server/tests/unit/evals/test_local_evals.py`、`test_local_evals_integrity.py`
  - `duxue-admin` `npm test`（52 项）与 `npm run build`

## 实现清单

- [x] 搭脚手架与明确 Stage 1 规格边界
- [x] 实现 `ModelDefinition` / `AdminBundle` / `ComponentSpec` / `complete_json_chat` 受控 Thinking 与遥测隔离
- [x] 升级 `math_executor/engine.py` 高中理科运算能力（复数、分数/符号幂、多元与含参方程组、不等式、初等/组合函数、向量）及四则快路
- [x] 解耦数学核验与答案泄露状态码、修复临时故障缓存、补齐本地受管子进程适配器与评测 preflight
- [x] 贯通 `Ward.grade_stage` 上下文、更新 `upgrade_math_bundle.py` 与 `evals/local` 汇总指标、同步 Admin 展示编辑与技术文档
- [x] 补齐全部单元测试并跑通 pytest / ruff / admin check（等待 Gate 2 用户验收）
