# DDD skill 通用指引审查

日期：2026-09-19。范围：分析 [skill](../../.cursor/skills/domain-driven-design/SKILL.md)、[模板](../../.cursor/skills/domain-driven-design/references/ddd-design-template.md) 与 README；未修改 skill。

- 既有指引已覆盖类型、所有权、触发矩阵、内部 UML、用例事务与失败语义；问题不是完全缺少流程/关系要求，而是局部契约未被要求连接为可追踪的完整过程。
- 建议通用补充：概念业务释义与实例、Workflow/阶段/Use Case 的关系、多步流程推进与等待恢复契约、状态权威来源、关系箭头语义、跨步骤实例验算；只在相关复杂度存在时要求。
- 模板仅为跨 Context 流程提供专门章节，遗漏单 Context 多轮/长流程的描述入口；不应因此把这类流程强行建模为跨域 Saga。
- 待统一：Process Manager 类型表允许跨请求/事件/时间，而正文收窄为仅多 Context；聚合外一律事件与同 Context 同事务协调规则冲突；跨 Context 一律事件与受权 API/ACL 集成描述冲突。
- 通用性约束：区分本 skill 的分类约定与普遍 DDD 原则；不得强制所有项目使用 Workflow、CQRS、Outbox 或 Python/Pydantic。局部审查应引用既有系统图而非重建全部交付物。
- 审查验收应检查读者能否追踪完整业务结果、分支、对象变化及恢复路径，而非仅检查表格/图是否齐备。建议以同步交易、同 Context 人工审批和跨 Context 异步流程验证 skill 的适用性。

仅分析和记录，无运行代码修改。

## 职责边界纠正

对照 [agent-design](../../.cursor/skills/agent-design/SKILL.md) 及其 workflow-runtime、设计模板后，收窄上述建议：不应给 DDD skill 增加必备的 Workflow 概述或运行设计章节。当前 Agent Workflow 的节点推进、等待恢复、Checkpoint、模型失败路径由 agent-design 指引，且其中已有明确要求；应先落实这些要求。

DDD 负责业务语义、聚合关系与生命周期、应用用例及其事务/领域调用契约。Agent design 负责如何编排和调用这些契约；业务规则仍以领域设计为唯一事实源。跨层协作与贯穿案例按两者关注点核对，不重复定义同一规则。普通非 Agent 的工作流也不因使用 Workflow 就归入 agent-design，其运行设计属于相应应用架构范畴。
