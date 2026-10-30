# 清空历史保留原始数据

日期：2026-10-30

事实源：[产品交互](../../docs/product/prd-companion.md#417-清空历史对话)、[服务端与客户端边界](../../docs/technical/domain-companion.md#清空历史与会话边界)。实现 spec：[clear-companion-history](../specs/done/clear-companion-history.md)，用户在迁移完成后要求提交，按本次提交验收通过归档。

- 用户明确要求只清空可见对话，不从数据库物理删除。采用 Ward/Thread 历史代次，避免逐消息删除标记；历史恢复、跨 Thread 分页、图片、事件和幂等重放必须一起检查代次，单清 App 气泡会重新恢复旧记录。
- 服务端清空命令复用 CompanionCommand，UUID 在接口边界规范化；同一命令重试不再推进代次，避免网络超时后重试误清新对话。入口接受、清空和回复提交使用 Ward 行锁；工作流后必须重新加载 ORM 状态，已有 identity map 不能证明旧 focus 仍有效。被拒绝的 Outcome 也不能通过原 HTTP 结果返回旧交互。
- App 允许清空正在生成的回复，所有在途聊天结果都受本地代次保护；finally 也要检查，防止旧请求结束时解除新会话的发送态。旧图片选择、历史加载和本地 Thread 写入同样要保护。
- TokenStorage 按序保存/清除 Thread。串行队列空闲时必须归零；长期保留一个已完成的 static Future 会在 Flutter 多个 fakeAsync zone 之间造成后续测试悬挂。队列用仅代表在途工作的 Completer，完成后释放。
- 迁移验证：隔离 SQLite 数据库模拟上一个版本，保留旧 Ward/Thread 行，升级 / alembic check / 回退 / 再升级 / check 全通过，旧行代次为 0。空库全历史迁移链在既有 `study_sessions ALTER COLUMN task_id DROP NOT NULL` 处不兼容 SQLite，未修改该旧迁移。随后按用户明确要求迁移实际数据库，见下节；PostgreSQL 并发行锁集成测试仍未执行。
- 验证：服务端完整回归 701 项通过，后续限定清空操作只处理当前代次的调整再通过 4 项相关测试；Flutter 完整回归 108 项通过，静态检查无问题；最终文字反馈修正后的 6 项匹配交互测试再次通过。

## 实际 PostgreSQL 迁移（2026-10-30）

- 用户要求直接使用 `duxue-server/.env` 中的连接配置执行迁移，不能以 SQLite 验证代替真实数据库迁移。显式加载该文件覆盖进程中的同名环境变量，未打印连接凭据。
- 实际库版本为 `20261029_29`，当前分支缺少对应迁移。在本地 `feat/specific-video-doc` 的提交 `a84e974` 找到原文件 `20261029_29_tutoring_video_answer_root.py`，原样补回迁移目录；没有修改/回退现有数据库版本，也没有删除既有视频答疑表。
- 将新增历史代次迁移编号调整为 `20261030_30`，前置版本为 `20261029_29`，已在 `.env` 指向的 PostgreSQL 执行成功。
- 验证：当前 revision 为 `20261030_30`；两个 `history_generation` 字段均 NOT NULL、默认 0，所有既有行初值为 0；Ward、Thread、消息、Run、Checkpoint、Trace、任务、StudySession 和视频答疑共 9 张表的迁移前后行数一致。
- 仅应用数据库 schema 迁移，未清空任何用户对话，应用代码尚未部署。
