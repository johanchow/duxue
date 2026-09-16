# CompanionMessage 统一入口实现

> 日期：2026-09-15

## 决策

- Ward 首页的语音计划协商和图片入口一律调用 `/companion/turn`；旧 Ward `plan-intake` HTTP 路由、客户端方法及其 API schema 已移除。`PlanIntakeService` 保留为 Planning Workflow 内部的任务/图片解析能力，不再是 HTTP 用例。
- 每个被接受的 Ward 输入和每个通过 Run/turn/attempt/focus fence 的最终 companion 文本各追加一条 `companion_messages` journal record。不会按语义合并历史；唯一约束只用于折叠命令重放或 Outcome 重复投递。
- 图片 OSS key 写入 Ward journal record。其生命周期与 transcript 相同，Ward 数据删除时先删除对象，再删除 journal 与 Thread；计划确认不会删除仍被聊天历史引用的图片。
- App 只在本地乐观展示 Ward 语音文本；成功后用 journal 刷新为“我 / 读学 AI”对话。发送失败保留原文本，并提供同一文本的重试入口。

## 验证

- 服务端：`127 passed`；Companion Coordinator、授权读取、附件引用和旧接口移除后的 E2E 覆盖通过。
- 迁移：本地 SQLite 从空库执行至 `20260914_17`，`alembic check` 无新增变更。
- App：`flutter analyze` 无问题，`flutter test test/app_ui_test.dart` 6 项通过。

## 注意

- 远端 RDS 的 DNS 在本地执行环境不可解析，因此未对该远端库执行 `alembic check`；本地迁移链已验证。
