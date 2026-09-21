# Planning 时间冲突与标题澄清

日期：2026-09-20

- 时间槽统一使用半开区间 `[start_at, end_at)`；`end_at = start_at + planned_minutes`。前一任务结束时刻等于后一任务开始时刻时相邻不冲突，严格交叉才产生 `time_overlap`。草稿审阅和确认事务都对草稿与现有正式日程的合并结果执行校验。
- 标题重名不使用正则、关键词命中、前缀或向量相似度。使用现有 `TaskReferenceResolver` 的可解释规范化：Unicode NFKC、大小写折叠、空白/有限标点归一化后做精确等价；引用解析的前缀匹配不参与标题冲突判断。
- 新增任务、修改标题、同一批次新增和兼容结构化接口统一执行标题冲突策略。冲突必须进入 `title_conflict` ClarificationSlot，由 Ward 选择 `use_existing`、`create_new`/`accept_duplicate` 或 `cancel`；模型不能生成 Task ID，适配器只在受权候选标题中解析已有目标。
- 兼容 `save_draft` 遇到同名标题返回结构化 409，避免静默复用；Planning 操作路径保留候选并等待澄清，确认前不写入重复或改名结果。
- 验证：Planning workflow 测试 28 passed；全量服务端测试 176 passed；相关文件 Ruff 与 `git diff --check` 通过。保留既有 FastAPI `on_event` 弃用警告。
