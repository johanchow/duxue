# Planning 内部对象与领域服务表

日期：2026-09-19；仅修改设计文档，未修改运行行为。

- 在 [Planning §2.1](../../docs/technical/domain-planning.md#21-aggregate-设计与状态变更) 补充 Entity Inventory、内部 UML 与独立 Domain Service 表；状态所有权和无状态规则分别表达，不合并为一张宽表。
- 目标方法与身份契约在正文唯一维护；明确与现有 `PlanningDomainService` 过渡实现的区别。排程图统一使用目标服务名，Workflow 阶段映射到 Application Use Case。
- 此次补充不解决上一轮审查中的全部问题，尤其没有修改确认门禁或实现聚合/服务拆分；后续实现仍需独立验收。
- 验证：审阅文档 diff、Markdown 表列数/围栏及本地链接检查，`git diff --check`；无运行时代码修改，不运行业务测试。
