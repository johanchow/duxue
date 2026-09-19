# Planning 本地日与确认冲突传播

日期：2026-09-19

- `PlanDraft.plan_date` 是 Ward 的产品日历日，当前固定按 `Asia/Shanghai` 计算；不能由 `datetime.now(timezone.utc).date()` 直接派生。UTC 只用于持久化时间戳。在上海零点到 UTC 零点之间混用两者会让 Graph 写前一天草稿，而 App 查询当天日程，进而产生 404 和错误的确认基准冲突。
- `HTTPException(409)` 是 Planning 的正常领域结果。Coordinator 必须让它回到 API，供 App 清除失效 action、刷新 thread/draft version；将其吞为 HTTP 200 workflow failure 会留下旧 action，下一次点击才变成误导性的 thread-version conflict。
- 引用解析不以“改/调整”等动词判断。模型的 `task_reference` 和 `title` 均为无 ID 的候选文字；服务端分别匹配、合并候选，只有唯一 Task 才 patch。模型 reference 的措辞不精确但 title 精确时仍可安全复用原 Task；多个候选仍澄清而不创建新任务。
