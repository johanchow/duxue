# Planning 战术 DDD 设计审查

日期：2026-09-19；依据：`.cursor/skills/domain-driven-design/SKILL.md` 与其设计模板。范围：审查，不改领域规格或代码。

- [Planning 设计](../../docs/technical/domain-planning.md) 已列 Task、PlanDraft、DailySchedule 三个聚合及根、部分内部对象、Repository 和本地事件；缺的是可执行的内部模型契约，不是完全没有 DDD 设计。系统 Domain Inventory / Context Map 已由 [DDD Overview](../../docs/technical/ddd-overview.md) 维护，无需复制。
- 非简单聚合缺完整 Aggregate Card、Entity Inventory 与 Internal UML；DraftItem/ScheduledItem 的身份、ClarificationBatch/Slot 的所属与生命周期、未登记 Candidate 的持久身份和转为 Task 的规则不充分。
- Graph 状态机不能代替 Task、PlanDraft、DailySchedule 的领域生命周期。WorkingState 混合业务状态、候选、运行时上下文与可派生读模型；应明确唯一事实源和字段类别。
- 时长修改时 Task 与草稿快照的权威性、三个聚合确认事务的并发保护、已有日程和本轮槽位共同冲突检查，需要按不变量说明。
- 本地事件已有名称，但缺按事件的所属根、触发行为、最小 payload、消费/持久化策略；仅在需要跨 Context 的稳定事实才映射 Integration Event，不应为补 DDD 引入事件总线或 Event Sourcing。
- 重要纠正：§四明确规定 `confirm_enabled` 要求“没有 pending Slot”。因此旧英语 Slot 阻塞数学确认部分符合当前书面全局门禁，不能全部称为实现偏离。它与“未安排任务可留池”“Batch 不抢占本轮意图”的规则需要澄清适用范围。回复丢失本轮数学变更仍是另一个独立问题。
- 建议明确待补项作用域、当前拟确认任务集合、本轮已应用变化和全局/单项阻塞原因；新增“数学已完整、英语缺时长、本轮只安排数学”的验收，分别约束 patch 保存、回复内容与确认资格。

最小改进：保留三个聚合的候选划分，先补其不变量/实体身份/生命周期/事件与事务契约；再将应用编排、Query 投影和 Infrastructure 映射分离。不要仅增加名词、图表或实体类数量。
