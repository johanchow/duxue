# 计划与任务

事实源：[计划 PRD](../../docs/product/prd-schedule.md)、[Planning 领域](../../docs/technical/domain-planning.md)。

## 目标

普通 Task 记事、Plan 按需提供顺序提示；首页不常驻当前/下一项，只有主动开启的限时 Sprint 展示挑战卡。完整规则归属 PRD，不要求孩子维护状态。

## 状态

- 2026-11-03 Gate 1 已获用户确认，已改造已有计划/任务功能并贯通独立 Sprint，当前待 Gate 2 验收；范围与实际证据见[进行中 spec](../specs/lightweight-planning-focus-sprint.md)。
- 已移除缺时长/钟点和未安排原因门禁；默认对话首页、按需已知作业、显式任务执行与无会话完成声明均有对应回归。
- 新增迁移 `20261103_32`，只在隔离 PostgreSQL 验证，未改开发/生产库、未部署。旧活动草稿失效，历史任务/会话保留。

## 决策索引

- 展示、可选估时、按需查看全部已知作业及邀请边界见 [PRD §三至四](../../docs/product/prd-schedule.md#三前台展示与入口)。
- 主动挑战的开启/到时与任务完成分离见 [PRD §4.4](../../docs/product/prd-schedule.md#44-专注挑战sprint)，执行归 [Study Sprint](../../docs/technical/domain-study.md#24-sprint主动专注挑战已实现待验收)。
- 安排/开始/完成分离、目标绑定、版本与幂等，以及迁移边界见 [领域设计](../../docs/technical/domain-planning.md)。
- 净书写、会话计时、完成耗时不得混用；证据边界见 [Behavior](../../docs/technical/domain-behavior.md) 与 [Study](../../docs/technical/domain-study.md)。

## 迁移与复核注意

- 模型语义由版本化 `planning.intake.prompt.v4` / `companion.intent.system.v8` 解释；先经过受控协议再执行，不能改回关键词/正则路由。Prompt 改动同步锁与生成的流程文档。
- 普通计划确认不创建会话或 Sprint；`timebox` 也不自动开启挑战。`duration_kind/duration_source` 可空，旧估时不回填来源。
- Sprint 与任务计时分开记账，使用 Ward 行锁、乐观版本、幂等回执和数据库单活跃轮次索引；到时不结束原学习会话或完成任务。
- 已有 Sprint/学习记录的任务不可物理删除；清除 Ward 数据须清挑战/回执与关联 Outbox。
- 服务端从执行区间计算时间，旧会话端点继续兼容，但不能信任客户端上报秒数。没有会话的完成声明只记 `TaskCompletionDeclared.v1`，不能伪造执行区间。
- 只有 `slot_source=ward_explicit` 的钟点可邀请；旧来源不明的槽位不冒充新授权。跨日保留历史且不重开旧挑战。
- 计划提示词变量用 `{{name}}`，JSON 示例不参与插值；Dart 时区展示使用上海偏移，未知时间不显示19:00或30分钟回退。

- 2026-11-03 自动化收敛：服务端764通过（1项既有网关二进制测试跳过）、Flutter118通过及静态分析通过；6条真实模型样例通过。待 Gate 2 人工验收，未部署、未迁移现有环境。

- 午夜回归注意：计划端到端测试的“今天”必须使用 `local_plan_date()`，不能用UTC日期；未选任务直接不放进安排项。`unscheduled_reason` 已退出门禁，也不表示排除任务，避免测试在上海00:00后把计划错误写到昨天。

- 2026-11-04 Ward改为安静首页，作业收更多菜单；口述挑战预览归Study独立只读流程，不读取Planning任务池，不创建/猜测当前Task。普通Companion挑战也允许缺主题，用通用标签，只在缺时长时追问。
