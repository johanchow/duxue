# Guardian 详情页今日计划

- Guardian 查看 Ward 详情时只读展示今日内容：若 `daily_plans.status=confirmed`，展示孩子确认后的计划项；没有已确认计划（包括无计划或仍为草稿）时，展示该 Ward 当前开放任务。
- 读取 `assignments` 和 `daily_plans` 扩展为 Ward 本人或已绑定 Guardian 均可访问；权限检查仍以 Ward 自身 ID 或 `guardian_ward_relations` 为准。保存与确认计划保持 Ward-only，Guardian 无法代为修改或确认。
- 详情页移除了重复的“传递任务”入口；任务传递固定从 Guardian 孩子列表的常驻入口发起，避免两个入口产生不同语义。
