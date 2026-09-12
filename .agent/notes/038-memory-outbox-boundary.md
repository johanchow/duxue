# Memory Evidence Ledger 与 Outbox 边界

- 上游 Context（Study、Tutoring、Reflection、Planning、Camera）在本地业务事务中只调用
  `publish_learning_fact` 写入自包含的 `LearningFactRecorded.v1` Outbox；不得直接创建
  `learning_events`。
- Memory Context 的 `SqlAlchemyMemoryCommandService.ingest_learning_fact` 是
  Evidence Ledger 的唯一写入口。消费者重试或重复投递由
  `source_type + source_id + event_type + source_version` 幂等键吸收，且不会重新发布来源
  Integration Event。
- `tutoring_episode` 的最小结算条件是同一 `tutoring_session_id` 的关闭 Fact 加至少一个
  有效交互 Fact（Ward 尝试、理解确认或实际提示）。孤立关闭、暂停和无活动不能生成 Episode。
- 验证：`duxue-server/.venv/bin/pytest tests -q`（40 passed）；`git diff --check`。
