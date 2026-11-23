---
slug: tutoring-workflow-reliability
created: 2026-11-23T08:24:45Z
status: in_review
---

# tutoring-workflow-reliability spec

## 做什么 / 为什么
修补 `ProblemSolving` × `Tutoring` 链路中阻碍提速与正确性的根因缺陷（后台建档事务竞态、无档案肯定门禁漏放、数学工具权限过宽），在此基础上落地精准后置建档与 Admin `tutoring.model_loop`（9→3 Action）/`tutoring-blueprint`（补齐 `START→select` 互斥入口、`select→finish` 整页误入短路与 `finish` 证据范围）精简改造，实现“先保可靠与正确、再砍冗余调用与长尾耗时”。

## 验收标准
- [ ] **P0-1 后台可靠投递与版本防覆盖**：
  - `RequestSolveCommand` / `ConfirmStemCommand` 仅在数据库事务提交后投递 Celery `solving` 任务（或经提交后回调/补投机制），消除 Worker 另开会话读不到刚 `flush` 记录而返回 `not_found` 的竞态；
  - `ExecuteDossierSolveCommand` 写回 `ProblemDossier` 时校验 `stem_version` 与租约，旧题面版本的迟到求解结果不能覆盖已确认的新版本；重复消费幂等；
  - 记录档案按时就绪/版本冲突/跳过的结构化观测指标。
- [ ] **P0-2 首轮无档案肯定门禁与数学证据权限拆分**：
  - 修复 `tutor_loop.py` 在缺少 `_dossier_gate` 时 `verdict_allowed` 默认 `True` 的漏洞：推理题无档案时禁止凭心算肯定最终答案或最优性；
  - 将断言权限拆分为局部步骤（`step_verdict_allowed`）与最终结论/最优性（`final_verdict_allowed`）：单条算术工具 `status=="ok"` 不再全局放行整题终值/最优性肯定（如过桥题算出某路线 19 分钟不能放行“19 分钟最短”）；
  - 新增“过桥题首轮无档案直问 19 分钟对不对”及局部算式可点评但最优性受拦截的回归测试。
- [ ] **P0-3 `tutoring-blueprint` 拓扑补边与证据扩展（保持 12 节点与兼容指纹）**：
  - `START` 两条出边均带互斥条件（`START → extract` 需首次读题 / `START → select` 已有可信题面）；
  - `select` Gate 接管 `bank_lookup`、`T0` 短路与 `worksheet_batch`（整页基础批改误入）短路出口至 `finish`（跳过求解不产出可信答案）；
  - `finish` 汇总输出本题面版本（`stem_version`）、目标小问、已证实断言及覆盖范围；
  - 旧已发布快照仍保持完全兼容加载与运行。
- [ ] **P1-1 统一后置精准建档（消除常识与整页口算无效入队）**：
  - 移除 `TutoringWorkflow._resolve_active_dossier` 在 `generate()` 前对新题的无条件 `RequestSolveCommand` 投递（仅保留只读缓存查询：已有 `dossier_id` 或命中 `ward`/`bank` 缓存）；
  - 在 `apply_work` 确认本轮为单道/题组推理题（非 `T0`、非整页多题基础批改）后再建档并提交后入队 `solving`；
  - 纯文字常识、闲聊、整页口算批改的 `solving` 后台入队次数为 **0**。
- [ ] **P1-2 `tutoring.model_loop` 拓扑精简（9 Action → 3 Action：`primary → repair → finish`）与按因限重试**：
  - 支持精简版 `tutoring.model_loop`（`primary`、`repair`、`finish`）与历史 9 节点快照双兼容；
  - 将文字泄露、数学不一致、配图泄露与缺图反馈统一收口至单次 `repair` 预算：复合失败（如同时泄题+缺图）合并反馈；仅图失败时严格锁住已审 `act/content/turn` 复用正文裁决；`math_unavailable` 时不盲目重跑同模型；
  - 提供幂等配置升级脚本（从当前测试草稿生成升级包，不破坏既有兼容指纹）并同步更新 `duxue-admin` 图展示/中文边标签。
- [ ] **（可选 P2，待 Gate 1 确认是否纳入本 spec）档案驱动续轮算力降档**：
  - 当 `active_dossier.status == "ready"` 且 `confidence == "high"` 时，续轮前台支持切换轻档位（关 Thinking），整页批改不默认开重 Thinking。
- [ ] **测试与规范退出条件**：
  - 服务端相关单元测试、架构/契约测试及全量非环境阻断套件全绿；Ruff 检查通过；
  - `duxue-admin` 单测、`typecheck`、构建全绿；
  - 相关技术设计文档（`domain-problem-solving.md`、`domain-tutoring.md`、`design-agent.md`）同步更新。

## 实现计划（Gate 1：填完等人确认，不许自转）

### 分步路线
1. **Step 1（P0-1：可靠投递与版本防覆盖）**
   - 在 `SqlProblemDossierRepository` / `RequestSolveCommand` / `ConfirmStemCommand` 中引入“事务提交后投递”（使用 SQLAlchemy `session.info` + `after_commit` hook 或显式提交后派发队列，失败留痕且支持租约过期自愈补投）；
   - `ExecuteDossierSolveCommand` 捕获求解起始的 `expected_stem_version`，写回时对比 DB 当前 `stem_version`，若已递增则安全放弃覆写并记录 `stale_stem_version` 指标；
   - 补真实事务提交顺序、重复消费幂等、旧版本不覆盖新版本单元测试。
2. **Step 2（P0-2：首轮无档案肯定门禁 + 数学工具权限拆分）**
   - 修改 `tutor_loop.py`：缺少 `_dossier_gate` 且当前为受保护作业/推理题时，默认 `final_verdict_allowed = False`（仅在非推理/非受保护或显式离线无档案兼容夹具按契约控制）；
   - 将 `verdict_assertion_allowed` 细分为局部步骤与最终结论断言权限，避免任意 `ledger.records` `status=="ok"` 解锁整题终值/最优性肯定；
   - 补“过桥题首轮无档案直问 19 分钟”“局部算式可确认但最优性受拦截”红绿回归测试。
3. **Step 3（P0-3：`tutoring-blueprint` 拓扑与 `select`/`finish` 升级）**
   - 在 `blueprint_steps.py` 与 `problem_solving.py` 中：
     - `START` 补齐互斥条件 `needs_extract` / `has_verified_stem`；
     - 将 `bank_lookup`、`T0` 短路与 `worksheet_batch` 误入短路收口到 `select` Gate；
     - `finish` 汇总输出 `stem_version`、`target_subproblems`、`verified_assertions`、`coverage`；
   - 保持旧 12 节点快照完全兼容，补充单元与拓扑校验测试。
4. **Step 4（P1-1：统一后置精准建档）**
   - 修改 `tutoring_workflow.py`：`_resolve_active_dossier` 仅做只读查询（已有 `dossier_id` 或只读命中 `ward`/`bank` 缓存），不再在 `generate()` 前对新题无条件入队；
   - `apply_work` 在通过出口检查且确认为单道/题组推理题（排除整页批量批改 `image_review.conclusion != "not_checking"` 且多题批改场景）后调用 `RequestSolveCommand`（提交后投递）；
   - 补充常识、整页口算、纯文字新题、单图新题 4 类入队行为回归测试。
5. **Step 5（P1-2：`tutoring.model_loop` 9→3 精简与复合修复）**
   - 在 `registrations.py` / `subworkflows.py` / `tutor_loop.py` 中兼容精简 3 节点拓扑（`primary`、`repair`、`finish`）与历史 9 节点拓扑；
   - 合并 `repair` 反馈（同时携带文字与缺失/泄露配图原因），保留“仅图失败锁正文复用裁决”，对 `math_check_failed`/执行器不可用避免无效同模型重试；
   - 新增/更新配置升级脚本与 `duxue-admin` 展示标签及单测。
6. **Step 6（文档同步与回归验收）**
   - 更新 `docs/technical/domain-problem-solving.md`、`docs/technical/domain-tutoring.md`、`docs/technical/design-agent.md`；
   - 跑通全量测试与静态校验，进入 Gate 2。

### 影响文件
- **服务端核心**：
  - `duxue-server/app/application/commands/problem_solving.py`
  - `duxue-server/app/application/ports/problem_solving.py`
  - `duxue-server/app/contexts/problem_solving/domain/dossier.py`
  - `duxue-server/app/workers/solving_tasks.py`
  - `duxue-server/app/application/workflows/tutoring_workflow.py`
  - `duxue-server/app/application/workflows/tutor_loop.py`
  - `duxue-server/app/agent_specs/blueprint_steps.py`
  - `duxue-server/app/agent_specs/registrations.py`
  - `duxue-server/app/agent_specs/subworkflows.py`
  - `duxue-server/app/agent_specs/catalog.py` / `admin_bundle.py`（如涉及条件白名单）
  - `duxue-server/scripts/upgrade_blueprint_steps.py` / 新增或更新 `tutoring.model_loop` 精简升级脚本
- **管理台（只同步新边标签与拓扑单测，不破坏旧图）**：
  - `duxue-admin/src/lib/workflow-graph.ts`
  - `duxue-admin/tests/workflow-graph.test.ts`
- **测试与文档**：
  - `duxue-server/tests/unit/problem_solving/test_solving_pipeline.py`
  - `duxue-server/tests/unit/problem_solving/test_blueprint_steps.py`
  - `duxue-server/tests/unit/tutoring/test_dossier_tutoring_integration.py`
  - `duxue-server/tests/unit/tutoring/test_tutor_turn_exit.py` / `test_leak_retry.py` / `test_visual_delivery.py`
  - `duxue-server/tests/unit/agent_specs/test_subworkflows.py` / `test_admin_bundles.py`
  - `docs/technical/domain-problem-solving.md`、`docs/technical/domain-tutoring.md`

### 测试计划
- 先红后绿新增以下回归用例：
  1. `RequestSolveCommand` 事务未提交前不派发、回滚不派发、提交后派发；`ExecuteDossierSolveCommand` 旧 `stem_version` 不覆盖新版本；
  2. 无 `_dossier_gate` 首轮推理题拦截心算终值肯定；单条算术 `ok` 仅允许局部步骤点评、不放行最优性肯定；
  3. `tutoring-blueprint` `START→select`（已有题面）触发 `bank_lookup` / `worksheet_batch` 短路；旧快照兼容运行；
  4. 常识题、整页口算批改 0 次入队 `solving`；纯文字/单图新推理题在 `apply_work` 精准入队；
  5. `tutoring.model_loop` 3 节点拓扑下：正常直出、文字泄露修后通过、仅图失败锁正文重绘、文字+缺图复合失败一次修复、旧 9 节点快照兼容；
- 运行 `duxue-server` 单元测试（`pytest tests/unit/problem_solving tests/unit/tutoring tests/unit/agent_specs` + 完整非 PG 初始化阻断套件）与 `ruff check`；
- 运行 `duxue-admin` `npm test`、`npm run typecheck`、`npm run build`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] P0-1：后台档案提交后可靠投递 + `stem_version` 防旧覆盖 + 回归测试
- [x] P0-2：无档案肯定门禁修复 + 局部步骤/最终结论断言权限拆分 + 回归测试
- [x] P0-3：`tutoring-blueprint` 互斥入口边、`select` 短路与 `finish` 证据扩展 + 回归测试
- [x] P1-1：`TutoringWorkflow` 统一后置精准建档（排除常识与整页口算）+ 回归测试
- [x] P1-2：`tutoring.model_loop` 9→3 拓扑兼容、复合修复合并与升级脚本 + Admin 标签同步 + 回归测试
- [x] P2：`ready+high` 续轮前台算力降档（关 Thinking / 轻档位）+ 整页批改不开重 Thinking + 回归测试
- [x] 文档同步 + 全量测试/Ruff/Admin 构建全绿
- [x] 导出升级包并导入本地测试 Admin 工作草稿（不发布）并回读校验

## 备注
- 工作区当前保留既有未提交改动（`tutoring.model_loop` / `tutoring.review_candidate` 命名统一等），本 spec 基于该现状增量开发，绝不回退或破坏已有改动。
- 涉及 `.env` / 测试 Admin 草稿导入操作，仅在用户明确授权后执行。
