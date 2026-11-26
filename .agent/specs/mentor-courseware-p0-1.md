---
slug: mentor-courseware-p0-1
created: 2026-11-26T10:36:37Z
status: draft
---

# mentor-courseware-p0-1 spec

## 做什么 / 为什么
落地成人导师视角深度课件 **P0-1（第一刀）**，实现从 `ProblemSolving` 客观核验到 `Tutoring.MentorCourseware` 交互式图文/3D 预置组件课件、对话式局部修订与毫秒级 Undo/Redo 的端到端闭环（设计唯一事实源见 [topic-mentor-courseware.md](../../docs/technical/topic-mentor-courseware.md)）。

- **包含范围（P0-1）**：
  1. Guardian「问答」页默认进入导师视角（`guardian_explain`）；由 AI 按题目复杂度自动分流（普通题直接快速讲清；有难度/需空间动态过程讲通的题在常规核验回复下方提供「生成深度课件」按钮）。
  2. 服务端 `Tutoring` 新增成人隔离聚合根 `MentorCourseware`（不可变版本链、`baseline_hash` 绑定、`state_revision` 单调 CAS、Undo/Redo 立即废弃旧在途任务并释放槽位）、领域服务 `CoursewareInvariantPolicy` / `CoursewareVersionPolicy`、Application Commands/Queries 与 `MentorCoursewareOrchestrator`（对接现有 `ProblemSolving`、`PedagogicalDirector`、`PedagogicalJudge`，DeepSeek/Qwen 异构选型）、Redis 4h TTL 仓储与 `/guardian/courseware/*` API。
  3. 端侧 `duxue-app` 新增离线 Web 舞台底座（本地打包 `Canvas2D + Three.js + KaTeX` + 4 语义色板 + 严格本地 CSP + 单一 `postMessage` 桥接）与首批 3 类预置常用组件（`component_scene`：平面坐标系与函数/动点、平面几何辅助线/翻折、3D 常见多面体截面/展开）+ 独立 Flutter 静态图文降级 + 折叠概览/单步微调/Undo-Redo 交互页；先以 **Android 真机**完成首轮渲染与交互验收。
- **明确不含（留待 P0-2 / P1）**：模型生成特殊演示 JS（`math_stage_script`）、服务端隔离 Headless 预运行容器与双端死循环故障恢复原型（P0-2）；逐 Beat TTS 音轨同步与 PostgreSQL 持久化（P1）；同源 MP4 导出（P2）。

## 验收标准
- [ ] **AC-1（默认视角与难度分流）**：Guardian 打开「问答」默认进入 `guardian_explain`（可自由切换 `student_guide`）；普通简单题直接快速返回；有难度或需空间/动态讲解的题返回常规核验回复并携带「生成深度课件」入口。
- [ ] **AC-2（两段式交付与预置动态渲染）**：点击「生成深度课件」后，阶段 1 完成即可看到核验结论与题眼速览；阶段 2 发布 `v1` 后，客户端展示折叠概览并支持展开步骤，在 Android 真机离线 Web 舞台中流畅渲染首批 3 类 `component_scene`（2D 坐标函数/动点、平面几何、3D 多面体旋转/截面/展开），无外网请求。
- [ ] **AC-3（对话式局部修订与哈希保真）**：针对某一步发起表达类修订（删减/拆细/补类比/调口吻）时，跳过 `ProblemSolving` 求解，仅重编并重渲受影响步骤，未改动步骤的 `step_id`、正文与媒体哈希保持不变；生成 `v2` 后 `can_undo=true`。
- [ ] **AC-4（数学纠错/换法诚实核验）**：修订涉及纠正结论或更换解法时，重新调用 `ProblemSolving` 确定性引擎复核；引擎判定原解正确时拒绝标记为 `verified`，仅在用户显式确认 `allow_unverified_override=true` 后生成 `unverified_custom` 草稿。
- [ ] **AC-5（Undo/Redo 确定性与并发 ABA 防护）**：Undo/Redo 纯本地短事务零模型调用；在途修订期间执行 Undo/Redo 立刻释放 `active_revision_id` 并推进 `state_revision`，迟到 Worker 发布必返 `409 revision_base_changed` 且不破坏历史；不同版本绑定不同 `baseline_hash` 时 Undo/Redo 零串味；历史节点新修订正确截断旧 Redo 分支且 `version_no` 单调不复用。
- [ ] **AC-6（单步故障降级与域隔离）**：任一步 `component_scene` 渲染异常时仅该步降级为 Flutter 侧已审核静态图文，宿主 Undo/Redo 正常可用；全部课件操作不写任何学生域表，不向 `Memory` 发布任何事件。
- [ ] **AC-7（自动化测试与静态检查全绿）**：服务端单元测试（领域不变量/并发 CAS/编排分流/API 契约）+ 客户端 widget/单测 + Android 真机首轮实测（含包体积增量、首帧耗时、3D 交互流畅度记录）全部通过。

## 实现计划（Gate 1：填完等人确认，不许自转）

### 影响文件
1. **服务端 Domain 层（`duxue-server/app/contexts/tutoring/domain/`）**：
   - 新增 `mentor_courseware.py`：`MentorCourseware` 聚合根、`CoursewareVersion`、`CoursewareStep`、`VisualSpec`（`component_scene` / `layered_svg`）、`VerificationBaseline`、`CoursewarePatch`、`CoursewareInvariantPolicy`、`CoursewareVersionPolicy` 及领域事件/异常。
2. **服务端 Application 层（`duxue-server/app/application/`）**：
   - 新增 `ports/mentor_courseware.py`：`MentorCoursewareRepository`、`ProblemVerificationPort`、`PedagogicalDirectorPort`、`PedagogicalJudgePort`、`CoursewareMediaRenderPort`。
   - 新增 `commands/mentor_courseware.py` & `queries/mentor_courseware.py`：`CreateMentorCourseware`、`AttachVerificationBaseline`、`RequestCoursewareRevision`、`PublishCoursewareVersion`、`UndoCoursewareVersion`、`RedoCoursewareVersion`、`FailCoursewareProduction`、`GetMentorCoursewareView`、`GetCoursewareProductionStatus`。
   - 新增 `process_managers/mentor_courseware_orchestrator.py`：跨 `ProblemSolving` 与 `Tutoring` 的三类场景分流编排与 Celery 异步任务入口。
   - 更新 `workflows/guardian_mentor.py`：输出是否推荐生成深度课件的结构化建议标记（`recommend_courseware`）。
3. **服务端 Infrastructure & Interface 层（`duxue-server/app/`）**：
   - 新增 `infrastructure/repositories/redis_mentor_courseware.py`（4h TTL + 原子 `state_revision` CAS）。
   - 新增 `infrastructure/ai/mentor_courseware_adapters.py`（DeepSeek/Qwen 异构 Director 与 Judge 适配器、`component_scene` Schema 校验与降级适配器）与 `agent_specs/mentor_courseware_contracts.py`（Admin 组件契约）。
   - 新增 `api/v1/guardian_courseware.py` 并注册 `/guardian/courseware/*` 路由（沿用现有成人鉴权）。
4. **客户端（`duxue-app/`）**：
   - 更新 `pubspec.yaml`：接入受控 WebView 插件与本地离线 `assets/math_stage/` 资源。
   - 更新 `lib/features/guardian_question_page.dart`：默认进入 `guardian_explain` 视角，在 AI 推荐深度课件的回复下展示「生成深度课件」入口。
   - 新增 `assets/math_stage/`：锁定版本的离线 `Three.js + KaTeX + Canvas2D` 运行时、4 语义色板与首批 3 类预置 `component_scene` 渲染器（2D 坐标函数/动点、平面几何、3D 多面体旋转/截面/展开）+ `postMessage` 桥接。
   - 新增 `lib/features/guardian_courseware/`：`GuardianCoursewarePage`、`CoursewareController`（Riverpod）、折叠概览、三联步骤卡片、Web 舞台宿主封装（含异常降级为静态图文）、底部 `VoiceComposer` 锚定 `target_step_id` 修订与顶部 Undo/Redo 栏。

### 测试计划
1. **服务端单测（`duxue-server/tests/unit/tutoring/test_mentor_courseware_*.py`）**：
   - 领域层：版本不可变、Undo/Redo 越界与分支截断、`version_no` 单调、`state_revision` CAS 与 ABA 迟到发布拒收、Undo 立即释放 `active_revision_id`、跨版本 `baseline_hash` 隔离、核验诚实门禁（禁止未核验标 `verified`）。
   - 应用与编排层：新题两段式编排、表达类修订跳过求解且未改动步骤哈希不变、纠错/换法触发 `ProblemSolving` 复核、审稿打回有界重修 1 次、学生域零写入断言。
   - 接口层：`/guardian/courseware/*` 鉴权、跨账号 `403`、幂等 `command_id` 与冲突 `409`。
2. **客户端测试（`duxue-app/test/`）**：
   - `GuardianQuestionPage` 默认进入导师视角与推荐按钮显示回归测试；
   - `GuardianCoursewarePage` 折叠概览、Undo/Redo 乐观状态、`STAGE_ERROR` 单步静态降级 widget 测试。
3. **联调与真机验收（Android）**：
   - 使用 3 道代表题（平面几何最值/函数动点、立体几何截面展开、语文/简单题反例）在本地联调环境跑通端到端生成、对话局部修订与 Undo/Redo，并在 Android 真机实测包体增量、首帧耗时、3D 旋转流畅度与无外网请求。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] **Step 1**：服务端 `MentorCourseware` 领域模型、值对象与 `CoursewareInvariantPolicy` / `CoursewareVersionPolicy` + 领域单测全绿
- [x] **Step 2**：服务端 Application Ports / Commands / Queries + Redis 4h TTL CAS 仓储 + 并发/ABA 单测全绿
- [x] **Step 3**：服务端 `MentorCoursewareOrchestrator` + `ProblemSolving` ACL + Admin 组件契约（DeepSeek/Qwen Director & Judge + `component_scene` 校验）+ 编排单测全绿
- [x] **Step 4**：服务端 `/guardian/courseware/*` API 与 `guardian_mentor` 难度分流推荐标记 + 接口测试全绿
- [x] **Step 5**：客户端离线 `assets/math_stage/` 运行时与首批 3 类预置 `component_scene`（2D 坐标动点、平面几何、3D 多面体）构建与本地验证
- [x] **Step 6**：客户端 `GuardianQuestionPage` 默认导师视角 + `GuardianCoursewarePage`（折叠概览、Web 舞台宿主、静态降级、单步修订、Undo/Redo）+ Flutter 测试全绿
- [ ] **Step 7**：Android 真机端到端联调验收（3 类代表题 + 对话修订 + Undo/Redo + 包体/性能实测记录）

## 备注
- 本文为 **Gate 1（计划确认）** 稿，等待用户确认后再进入 Step 1 编码。
- P0-1 完成后，再单开 `mentor-courseware-p0-2` spec 实施模型生成 JS（`math_stage_script`）、服务端隔离 Headless 预运行与双端故障恢复原型。
