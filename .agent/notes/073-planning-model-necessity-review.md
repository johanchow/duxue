# Planning 对象与服务必要性复核

日期：2026-09-19。范围：依据 [DDD skill](../../.cursor/skills/domain-driven-design/SKILL.md) 复核 [Planning §2.1](../../docs/technical/domain-planning.md#21-aggregate-设计与状态变更)，不修改设计契约或运行代码。

- 内部清单有助于明确状态所有权，但不要求每行对应独立类、表或 Repository。实体身份应由跨轮业务连续性支撑；无状态服务应由无法自然归属单个领域对象的规则支撑。
- 待修正：项以 task_id 为唯一身份、每任务只能一个时间槽的约束，与 [计划 PRD §4.1.2 / §4.1.4](../../docs/product/prd-schedule.md) 已要求的任务拆分冲突。应明确缩减产品范围，或设计独立安排项身份及分段时长、引用规则。
- 待澄清：ArrangementIntent 与 DraftItem 内意图的唯一事实源；ClarificationBatch 的业务待补状态与 response_mode 交互配置边界；必做任务暂不安排原因的本次计划归属；Task 时长变化对审阅版本和确认的影响。
- 两个目标领域服务有业务依据，无须强制拆出更多服务。TaskReferenceResolver 的候选加载、授权与会话上下文提取仍属应用层；SchedulingService 的校验不能替代根对正式日程合法性的保护。
- 确认涉及多个本 Context 聚合，不能仅因同事务就判定错误；需补足草稿、日程及相关 Task 版本保护。旧 pending Slot 的全局确认门禁仍按 [前次审查](071-planning-tactical-ddd-review.md) 所述待明确，本次不改变。

验证：核对文档、PRD 与现有服务依赖；只新增审查笔记，无行为修改。
