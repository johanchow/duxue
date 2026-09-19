---
slug: align-companion-planning-protocol
created: 2026-09-16T00:00:00Z
status: draft
---

# align-companion-planning-protocol spec

## 做什么 / 为什么

将当前 Companion 与 Planning 的实现对齐 `domain-companion.md` 的
`companion-interaction.v1` 与 `domain-planning.md` 的「任务先入池、确认后入日程」模型。淘汰
`planning_confirm`、宽松 `planning_items` 及确认时创建任务的旧路径，同时在一个兼容窗口内维持
现有 Ward 页面可用。

## 验收标准

- [x] 已验证的规划解析在拥有 `title + planned_minutes` 时立即、幂等地登记已有 `Task`；缺时长不创建；确认流程绝不创建 Task。
- [x] 草稿只引用已有 Task；`GetPlanDraft`/interaction 投影展示所有可见未完成任务及其时间槽、`will_enter_plan`、原因和 `confirm_enabled`。
- [x] 仅有完整时间槽、无冲突且至少一项可入计划的 Task 可被确认；确认再次校验草稿/日程版本，并以本地事务更新日程、Task 和 Outbox。
- [x] `/companion/turn` 支持 `TextTurn | StructuredWardCommand`；结构化命令只接受当前、启用且与 run/attempt/draft version 绑定的服务端签发 action，未知或过期动作返回 `409`。
- [x] Planning Outcome 返回受控 `companion-interaction.v1` 信封；App 按 `kind` 和 `object_ref` 拉取目标 Query，不再依赖 `interaction.items` 或发送 `planning_confirm`。
- [x] 旧请求字段仅作为服务端兼容 adapter；不再被新 App 使用，也不再扩展。现有聊天 journal、线程版本和命令幂等/late-outcome 防护继续有效。
- [x] 服务端单元、API/E2E 与 Flutter widget/API 测试覆盖任务登记、冲突、确认、旧 action 拒绝、协议渲染和兼容路径；新增多槽位澄清批次与 ORM migration；Alembic 远程数据库检查受 DNS 不可达影响未运行。

## 实现计划（Gate 1：填完等人确认，不许自转）

- 影响文件：
  - `duxue-server/app/api/schemas.py`、`app/api/v1/companion.py`：建立区分式 Turn DTO、受控 command、目标 Query 与错误映射；旧字段只走 adapter。
  - `duxue-server/app/application/process_managers/companion_coordinator.py`、`app/application/ports/companion.py`：保存/校验签发 interaction action，向工作流传递类型化 command，保持 Thread/run/attempt fence。
  - `duxue-server/app/application/workflows/planning_adapter.py`、`planning_workflow.py`、`planning_domain_service.py`：任务登记、草稿投影、时间槽/冲突重校验、确认事务和标准 Outcome。
  - `duxue-server/app/infrastructure/persistence/models.py`、`migrations/versions/`：补充 action 发行记录及 Task/Draft 所需的最小持久化字段/约束；不破坏既有数据。
  - `duxue-server/tests/{unit,application,contract,integration}/...`、`tests/test_e2e.py`：覆盖上述领域、协议、授权、幂等及迁移行为。
  - `duxue-app/lib/core/api_client.dart`、`lib/features/day_story_pages.dart`、`test/app_ui_test.dart`：发送结构化 action、按 interaction 信封渲染并通过 object query 获取计划数据。
  - `docs/technical/design-server.md`、`.agent/notes/059-align-companion-planning-protocol.md`：物理映射、兼容期限及实现决策。
- 实施步骤：
  1. 先定义协议 DTO、action 发行/验证模型与 Planning Query 形状，写失败测试。
  2. 改造 Planning 服务：登记已验证任务、只以 Task ID 保存草稿、生成时间槽与确认列表，确认时仅安排已有 Task。
  3. 让 Workflow/Coordinator 产出并持久校验 `companion-interaction.v1`，保留旧字段到 adapter 的单向兼容。
  4. 迁移 App 至 `kind + object_ref + StructuredWardCommand`，保留 transcript 与错误恢复。
  5. 创建迁移，执行服务端/Flutter 检查，review diff，并写决策笔记。
- 测试计划：
  - 服务端：任务登记幂等、缺时长、重复/外 Ward ID、时间槽、冲突、空计划、草稿/日程版本冲突、confirm 不创建任务、action 重放/失效/禁用。
  - API/契约：TextTurn 与 StructuredCommand schema、未知 kind/command、目标 Query 授权与兼容旧字段。
  - App：计划确认卡从 Query 渲染、发送 action、409 后刷新、旧 interaction 不作为新路径依赖。
  - 检查：Python formatter/lint/pytest、Alembic upgrade/current/check、Flutter format/test/analyze、`git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）

- [x] 建立 spec 并完成影响分析
- [x] 定义/测试 Companion 受控交互与 action 授权
- [x] 实现任务池与草稿/确认领域迁移
- [x] 实现 Query 与旧字段兼容 adapter（本次无需 ORM migration）
- [x] 迁移 Flutter 调用与渲染
- [x] 补齐并通过自动化测试与静态检查
- [x] Review diff 并写入决策笔记

## 备注

- 设计真相分别位于 `docs/technical/domain-companion.md#52-companion-interaction-protocol` 与 `docs/technical/domain-planning.md`；本 spec 只记录本次实施范围和验收。
- 原有未提交的两份领域设计和 notes 属于本功能的设计输入，必须保留。
