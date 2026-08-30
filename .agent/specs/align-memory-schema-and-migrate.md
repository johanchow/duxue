---
slug: align-memory-schema-and-migrate
created: 2026-08-30T09:55:07Z
status: draft
---

# align-memory-schema-and-migrate spec

## 做什么 / 为什么
将 `duxue-server` 的 ORM、Alembic 与数据库结构对齐至 `docs/technical/design-server.md` 的目标 ER：使用 PostgreSQL 原生 UUID、无数据库级联删除、事实事件与记忆/信号链路、Transactional Outbox，以及由长期 Signal 聚合的 Profile 读模型。当前线上不应存在真实数据；迁移前必须只读确认该前提。

## 验收标准
- [x] 迁移前检查连接目标、当前 Alembic revision 与所有现有业务表记录数；如发现任何非系统/测试数据即停止，不执行破坏性结构替换。
- [x] 学习、任务、会话与记忆域的 ORM/Alembic 使用设计文档目标表名和 PostgreSQL `UUID` 主键/外键；已移除 `assignments`、`daily_plans`、`plan_items` 和 `study_messages` 作为运行时事实源。既有账户资料表 `user_guardians`/`user_wards` 继续承载角色扩展信息，保留在本次范围之外。
- [x] 所有目标外键均不配置 `ON DELETE CASCADE`；普通删除因引用关系被数据库拒绝，后续仅能通过显式应用级清理工作流处理数据擦除。
- [x] 建立 `learning_events`、`outbox_events`、`episodic_memories`、`episodic_memory_events`、`derived_signals`、`derived_signal_events` 和 `long_term_profiles` 的物理表、索引和幂等约束。
- [x] Signal 的最终证据来源仅为 `derived_signal_events`；不保留与其竞争的 `evidence_ids` JSON 事实源。
- [x] 任务池与计划项收敛为唯一 `tasks` 实体；`StudySession` 记录一次任务执行，`study_session_intervals` 记录每段开始/暂停/恢复区间，并以部分唯一索引保证单会话至多一个未关闭区间。
- [x] 通过 PostgreSQL 上的 Alembic upgrade、模型/约束集成测试、`alembic current` 与 schema 检查验证迁移结果；迁移后服务端测试全绿。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/models.py`：以设计 ER 的实体和 UUID 类型重建目标 ORM；移除所有 `ondelete="CASCADE"`；增加事件、Outbox、近期记忆、Signal、证据关系与 Profile 模型。
  - `duxue-server/app/main.py`、`dependencies.py`、`services.py`、`ai.py`：将当前 `user_wards` / `assignments` / `daily_plans` / `study_sessions` 等旧模型引用迁移到目标领域名称与关系。
  - `duxue-server/migrations/versions/`：新建目标 PostgreSQL schema 迁移；先只读检查空库和 revision，再在空库条件下显式替换不兼容的旧表结构，创建全部 FK、索引和约束；不采用 cascade。
  - `duxue-server/tests/`：迁移/模型/接口测试适配 UUID 和新名称，新增事件幂等、证据关系、无 Cascade 约束的覆盖。
  - `docs/technical/design-memory.md`、`docs/technical/design-server.md`：补齐生命周期编排、Outbox 物理表及最终实现边界，避免文档与迁移偏离。
  - `.agent/notes/`：记录空库替换、无 Cascade 删除与事件幂等的实施决策。
- 测试计划：
  - 在独立临时 PostgreSQL 数据库执行 `alembic upgrade head`，验证约束、UUID 类型、索引和禁止 Cascade。
  - 对目标 `.env` 仅执行只读预检（数据库身份、revision、表记录数）；仅当预检确认无真实数据时才执行 `alembic upgrade head`。
  - 运行仓库规定的 `duxue-server/.venv/bin/pytest tests -v`、`alembic current`、schema 查询和 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 建立 spec，核对当前 ORM、迁移链与目标 ER 的结构差异。
- [x] 补齐生命周期编排、Outbox 和删除/幂等边界的设计规范。
- [x] 收敛任务池/计划项为 `tasks`，并实现 StudySession 与多区间暂停恢复模型。
- [x] 重构 ORM、服务引用和测试至目标领域模型。
- [x] 编写并在独立 PostgreSQL 数据库验证 Alembic 迁移。
- [x] 对 `.env` 目标执行只读空库预检；通过后执行迁移并验证 revision/schema。
- [x] 写入实施决策、审阅 diff，等待验收确认后归档 spec。

## 备注
- 当前 `tasks` 与现有 `assignments + plan_items`、`daily_schedules` 与现有 `daily_plans` 并非纯改名关系。因用户确认线上无真实数据，本次采用“空库预检通过后替换为目标结构”的迁移策略；若预检发现数据，必须停止并重新制定保留数据的迁移方案。
