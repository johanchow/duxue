# Planning 受控 Agent Loop 设计

日期：2026-09-21

- `docs/technical/domain-planning.md` 先升级到 v1.9，后续收口到 v1.10：Planning 协商采用固定 Graph + 局部受控 `PlanningAgentLoop`，不采用全自由 ReAct。
- `Task` 创建与进入计划继续分离：`title + planned_minutes` 即可创建并进入未排期列表；只有 Ward 明确给出 `start_at` 或可由明确顺序推导时才写入草稿计划。
- `PlanningAgentLoop` 通过窄工具完成多操作提取、任务引用解析、重复名检查、Task 创建/修改、草稿 patch 和澄清建立；模型不能生成 Task ID、不能判定无冲突、不能确认正式计划。
- 新增 `OperationResultReview` 概念，用于展示本轮已保存、未排期、已入草稿、待澄清、被拒绝和失败操作，避免只回复最后一个澄清问题。
- 明确 loop 退出状态：`draft_changed`、`task_pool_changed_only`、`needs_clarification`、`partial_success`、`no_op`、`rejected`、`tool_error`、`loop_limit_exceeded`。
- 2026-09-21 追加：主 Workflow 图收敛为顶层阶段图，内部判断、版本复核和事务写入不再作为顶层节点；另补 `PlanningAgentLoop` 内部工具循环图和节点级完整工具授权表。
- 2026-09-21 追加：删除 §二 的重复阶段表；§四合并工具分组、节点授权和 Loop 退出条件为单张 Workflow 节点表，直接标注 AI-driven 边界、Loop/等待类型、满足条件和全部工具。
- 2026-09-21 追加：按文档审阅收口，保留三张对象职责 UML（创建任务、进入计划、局部 Patch），删除重复引用解析图、触发表、确认大时序图和长 Gherkin 清单；修正主图修订入口和旧入口命名。
- 2026-09-21 追加：`docs/technical/domain-planning.md` 升级到 v1.10，全文压缩到 500 行以内。
- 2026-09-21 追加：实现对齐时保留现有确定性 `PlanningOperations.apply_operations`，新增持久化 `working_state.planning_agent_loop`，并在 `plan_draft_view` 暴露；覆盖 `draft_changed`、`task_pool_changed_only`、`needs_clarification`、`partial_success`、`no_op`、`rejected` 六类当前可由本地工具确定的退出状态。
- 2026-09-21 追加：新增测试确保 `title + planned_minutes` 只进入任务池；显式 `start_at` 才进入可确认计划；多操作部分成功时既保留已保存结果又继续澄清；全拒绝与空轮次不会被误判为可确认草稿。
