# DDD Skill 最小类型体系

- `.cursor/skills/domain-driven-design` v2.3 将设计概念收敛为通用最小类型体系：Actor、Interface、Use Case、Query、Process Manager、Aggregate Root、Entity、Value Object、Domain Service、Domain Event、Integration Event、Read Model / Projection 与 Infrastructure。
- `Command` 仅作为 Use Case 的输入 DTO；不再作为架构概念类型。Skill 同时要求 Workflow、Handler、Worker 等实现命名映射回其拥有职责的最小类型。
- 新增类型间允许关系：Interface/Worker 只能进入 Use Case 或 Query，跨 Context 必须通过 Integration Event 与接收方 Use Case，Projection 不可成为写入权威。
- Skill 与模板使用通用术语，不纳入本项目的 LearningEvent、Signal、Memory 等领域名称；每个项目应在自身 Ubiquitous Language 中完成映射。
