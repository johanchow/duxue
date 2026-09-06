# DDD Skill 结构

- `.cursor/skills/domain-driven-design` 的 DDD Skill 升级为执行型 v2：入口只保留战略 DDD、层级边界、设计流程和交付要求；详细设计骨架放入 `references/ddd-design-template.md`。
- 聚合只承载实体、值对象、不变量、领域行为和领域事件；Command、Application Service、CQRS Query 与 API 是所属 Bounded Context 的应用/接口层，不能写作聚合成员。
- 跨 Context 默认通过版本化 Published / Integration Event、ACL 或拥有真实流程状态的 Process Manager 协作；禁止 Application Service 直接写另一个 Context 的聚合。
