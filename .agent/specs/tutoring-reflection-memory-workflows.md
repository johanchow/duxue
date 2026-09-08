---
slug: tutoring-reflection-memory-workflows
created: 2026-09-07T17:28:20Z
status: draft
---

# tutoring-reflection-memory-workflows spec

## 做什么 / 为什么
将目前仅有的旧答疑消息/自评接口收敛为受控的 Tutoring、Reflection 与 Memory
application workflow：Coordinator 只路由到一个 Run；各 workflow 才能写本 Context
事实，并经版本化 Outbox 驱动情境记忆、候选 Signal 与长期画像投影。模型仍只能产出
被校验的候选；首版必须在没有模型可用时保持安全、启发式降级，不能伪造 AI 推理。

## 验收标准
- [ ] `POST /companion/turn` 可用受权 `study_session_id` 和类型化
  `session_directive` 启动/续接/关闭一个 Tutoring Run；不允许跨 Ward 会话、关闭后继续
  教学、未知指令、未授权工具或超预算。直接索要答案/代写被确定性拦截并只返回启发式
  首步；每个已验证的 Ward 尝试、提示、关闭均写学习事实与 `LearningFactRecorded.v1`。
- [ ] Reflection workflow 仅在 Ward 提交类型化自评后创建/更新 `SelfReview` 与
  `FocusKit`；返回的 View 明确标示行为证据是否已到达，且提交前不透传客观行为时间轴。
  采纳 Focus Kit 需显式指令并产生独立学习事实。
- [ ] Memory Consumer 对 `LearningFactRecorded.v1` 进行 schema/来源四元组幂等校验；
  关闭的 Tutoring Session 能从事实账本结算一个带证据链接、聚合引用、版本和热窗口的
  `tutoring_episode`，不复制完整聊天或 Runtime State。
- [ ] 受控 Worker 只能提出 Candidate Signal；Ward 纠正将其转为 Challenged 并追加
  counterevidence；每日演进仅将满足 Policy 的长期 Signal 激活/过期。Profile 始终由
  active + long-term Signal 全量重建，Candidate/Challenged 不得出现。
- [ ] 新增 schema migration（不使用 Cascade）、领域/Worker/API 测试和回归测试；在
  SQLite 与 PostgreSQL Alembic upgrade 上通过，完整服务端测试与 diff 检查通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/models.py`、`migrations/versions/<revision>_memory_aggregates.py`：
    为 episodic memory 增加 `memory_type`、`aggregate_ref`、`aggregate_version`、热/过期/
    归档窗口和唯一聚合键；为 Signal 增加 `dimension_key` 与合法 identity；将证据链接
    唯一键扩展到 role。全部 FK 保持 `NO ACTION`。
  - `duxue-server/app/ai_agents/tutoring_*`、`reflection_*`：实现领域应用服务和无模型时
    的确定性启发/安全策略；模型接入只预留 `OutputValidator` port，不能直接写 ORM。
  - `duxue-server/app/ai_runtime/contracts.py`、`workflow_dispatcher.py`、
    `companion_coordinator.py`、`schemas.py`：加入类型化 tutoring/reflection Turn 字段、
    `RunInvocation` 传递、目标 workflow 注册和结构化 Outcome。
  - `duxue-server/app/memory.py`、`infrastructure/messaging/celery_tasks.py`：实现入站事实
    校验、会话情境结算、Candidate/Challenge/Evolve、Profile 重建以及可重试的 Worker
    entrypoint；Consumer 不重新发布来源事实。
  - `duxue-server/app/main.py`：保留兼容旧端点，但将新 Companion workflow 作为唯一新
    编排入口；不在 Coordinator 直接改 Tutoring/Reflection/Memory 表。
  - `duxue-server/tests/test_tutoring_workflow.py`、`tests/test_memory_lifecycle.py`、
    `tests/test_e2e.py`、`.agent/notes/`：覆盖安全、授权、幂等、结算、反证、投影和 API。
- 测试计划：
  - 先写纯领域/应用测试：答疑四级提示上限、反代写、关闭 guard、事实 Outbox、
    episode evidence 去重、Candidate 不投影、Ward Challenge 和 Signal 到期。
  - 以 fake Dispatcher/Model Gateway 运行 Coordinator API 测试；无网络、无真实模型。
  - 在 SQLite 跑 API 回归；在独立 PostgreSQL 执行 `alembic upgrade head`、约束和
    `alembic check`，不对未确认有真实数据的库执行结构替换。
  - 最后运行 `duxue-server/.venv/bin/pytest tests -q`、迁移检查与 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [ ] 先补 Memory Aggregate 字段/迁移与证据约束，并用 PostgreSQL 验证。
- [ ] 实现 Tutoring workflow、确定性安全/启发 Validator、Session 事实与端到端测试。
- [ ] 实现 Reflection workflow、显式 Focus Kit 采纳与带证据版本的返回 View。
- [ ] 实现 Memory consumer、episode settlement、Signal challenge/evolution 和 Profile rebuild。
- [ ] 完成 Worker/API/迁移集成测试、决策笔记与 diff 审阅。

## 备注
- 首版不接真实模型或通用外部工具：它们没有可验证的 Policy/审批/预算实现。实现将用
  确定性安全降级来保证“不代答”这一不变量，后续模型只能通过 `OutputValidator` 接入。
- 旧 `/sessions/{session_id}/messages` 和 review API 是已发布兼容入口；本阶段不能删除，
  但不再将它们扩展为新的 Agent 编排路径。
