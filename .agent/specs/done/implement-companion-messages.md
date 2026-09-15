---
slug: implement-companion-messages
created: 2026-09-14T00:00:00Z
status: done
---

# implement-companion-messages spec

## 做什么 / 为什么

实现已确认的 `CompanionMessage` Ward-facing transcript：学生首页通过 VoiceComposer 发出的最终语音转写以“我”展示，服务端以独立、追加式消息记录持久化该 Turn 与已校验的“读学 AI”回复，页面刷新后可按 Thread 恢复和继续展示历史。

## 验收标准

- [x] 服务端新增 `CompanionMessage` transcript journal store 与迁移；只允许 `author_type=ward|companion`，以 Thread version 排序，具备命令幂等和 Ward 授权查询所需的约束/索引。
- [x] `POST /companion/turn` 在接受 Ward Turn 的同一短事务追加 Ward 消息；可展示的 Workflow Outcome 经过 run/turn/attempt/focus fence 后在 Outcome 事务追加最终 companion 消息；重试及迟到 Outcome 不重复或错序写入。
- [x] 新增认证 Ward 专属的 Thread 消息分页读取接口，返回 `thread_version` 有序的 Ward-facing transcript，禁止跨 Ward 访问；不得返回 system prompt、Trace、Checkpoint、模型推理或未校验数据。
- [x] App 的 Ward 首页改用 Companion 统一入口：VoiceComposer 最终转写立即显示为“我”的消息，服务端回复显示为“读学 AI”的消息；初始加载/重新打开对话可恢复历史，计划草稿/确认交互仍可工作。
- [x] 计划协商仍保留 Ward 明确确认权、附件上传与任务池行为；新实现不新增文字输入入口，也不改 VoiceComposer 手势语义。
- [x] `docs/technical/design-server.md` 补充 `companion_messages` 的物理模型、关系、索引与数据删除边界；实现与 `domain-companion.md` 一致。
- [x] 服务端单元/E2E 与 Flutter widget/API 测试覆盖保存、读取、授权、幂等/迟到防护及 Ward/AI 气泡；相关检查全绿。

## 实现计划（Gate 1：填完等人确认，不许自转）

- 影响文件：
  - `duxue-server/app/infrastructure/persistence/models.py`、`duxue-server/migrations/versions/`：新增 append-only `companion_messages` 模型、迁移、外键与索引。
  - `duxue-server/app/application/process_managers/companion_coordinator.py`、`duxue-server/app/application/ports/companion.py`：在现有两段短事务中追加 Ward/companion message，暴露 Query DTO，保持 command/focus/attempt fence。
  - `duxue-server/app/api/v1/companion.py` 及 schemas：新增 Thread message cursor API，并让 `/companion/turn` 返回可供客户端关联的 Thread/Turn 数据。
  - `duxue-server/app/api/v1/identity.py`：将 `CompanionMessage` 纳入 Ward 删除清理顺序。
  - `duxue-server/tests/...`：补 Coordinator 单元和 API/E2E 覆盖。
  - `duxue-app/lib/core/api_client.dart`、`duxue-app/lib/features/day_story_pages.dart`：调用统一 Companion API、加载分页历史、维护 optimistic/sending/failed message UI，并继续呈现计划草稿卡片。
  - `duxue-app/test/app_ui_test.dart`、必要的 API client tests：覆盖 Ward/AI 气泡、历史恢复与失败/重试。
  - `docs/technical/design-server.md`、`.agent/notes/055-implement-companion-messages.md`：维护物理设计和实现决策。
- 实施步骤：
  1. 先补物理设计、journal store、迁移与服务端 Query DTO/store helper；用迁移和模型测试验证 schema。
  2. 在 Coordinator 的 accepted Turn 与 fenced Outcome 事务中追加消息，并实现分页、授权、删除清理与幂等测试。
  3. 将 Ward 首页从 legacy plan-intake 请求迁移到 `/companion/turn` 的 planning route，保留草稿/确认结果映射，并接入历史查询。
  4. 完成 Ward/AI 气泡、发送/失败/重试和附件提示 UI，补 Flutter widget 测试。
  5. 执行格式化、服务端测试/迁移检查、Flutter 测试与静态检查，review diff，沉淀决策。
- 测试计划：
  - 服务端：CompanionCoordinator 单测 + `/companion/turn`、messages cursor、跨 Ward 403/404、同 command id 幂等、迟到 Outcome 不写 AI message、Ward 删除清理。
  - App：Widget 测试验证语音最终文本出现“我”气泡、AI 回复追加、重载历史、失败后可重试；保留现有 VoiceComposer、计划草稿和任务池回归。
  - 检查：迁移 upgrade/current/check、pytest、`flutter test`、`flutter analyze`、`git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）

- [x] 建立实现 spec 并完成影响分析
- [x] 设计物理模型与创建迁移
- [x] 实现服务端写入、读取、授权和删除链路
- [x] 迁移 Ward 首页至 Companion API 与 message UI
- [x] 补齐服务端和 Flutter 自动化测试
- [x] 执行格式化、迁移、测试、静态检查与 diff review
- [x] 写入实现决策笔记

## 备注

- Ward 首页不再保留旧 `plan-intake` endpoint 或客户端调用；计划解析保留为 Planning Workflow 内部能力，统一由 `/companion/turn` 调用。
- `CompanionMessage` 不引入 `system` author type，也不保存/返回 prompt、CoT、Trace、Checkpoint 或原始工具输出。
