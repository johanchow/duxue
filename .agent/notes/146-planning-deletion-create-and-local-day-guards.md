# Planning 删除、新增与本地计划日门禁

日期：2026-10-21

- 现象：Ward 可通过直接接口和自然语言删除 `source=guardian` 的必做 Task；新增任务的相对时间引用被拒绝或开始时间格式待澄清时，Task 已经入池；草稿 `plan_date` 与时间槽本地日不一致仍可确认。
- 根因：删除用例只检查状态和学习记录，遗漏来源权限；新增操作先登记 Task 再校验时间引用；排程校验只检查重叠与容量，没有校验 `start_at` 的本地日。
- 修复：直接删除、Agent 删除和修订确认均拒绝删除 Guardian Task；新增操作先校验时间引用与格式，再登记 Task；草稿视图和确认共用的排程校验按 `Asia/Shanghai` 检查开始时间是否属于 `plan_date`，以 `wrong_plan_date` 阻止确认。
- 回归：测试覆盖三条删除路径、被拒绝或待澄清的新增不入池、跨日本地时间与 UTC 偏移时间不可确认；旧测试中表示 Ward 自建任务的 fixture 明确标为 `source=ward`，今天的时间槽使用同一 `planning_today()`。
