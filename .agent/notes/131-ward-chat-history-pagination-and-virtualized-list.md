# 131 Ward 首页历史对话无限上滑分页与 ListView 视口分窗口渲染

日期：2026-10-19

事实源：`docs/technical/domain-companion.md` §5.1。

- 问题：
  1. Ward 首页 `_planChatOverlay` 原本每次只拉取当前 `companionThreadId` 的最新 50 条消息，不支持上滑分页加载更早消息；
  2. 当设备重绑（`TokenStorage.saveWard` 清空 `companion_thread_id`）或启动偶发网络抖动时，本地丢失 `threadId`，无法看到之前的历史消息；
  3. 聊天弹层 `_HomeOverlay` 原本使用 `SingleChildScrollView` + `Column` 全量构建所有气泡 Widget，历史消息增多时会影响客户端渲染性能。
- 决策与改动：
  1. **保持 LLM 上下文窗口不变**：后端 `run_transcript.py` 的 `select_recent_utterances`（`MAX_UTTERANCES = 8`、`MAX_UTTERANCE_CHARS = 2400`、`MAX_WINDOW_IMAGES = 8`）完全不变，前端加载多少历史消息都不影响大模型交互窗口。
  2. **服务端最近会话恢复与跨 Thread 历史衔接（`app/api/v1/companion.py`）**：
     - 新增 `GET /companion/threads/current/messages`，当客户端本地没有保存 `companionThreadId`（如重新绑定或换设备）时，自动定位该 Ward 最近有消息的 `ConversationThread` 并返回最新页与 `thread_id`/`thread_version`；
     - 当某个 Thread 内部游标翻到顶（`next_before_thread_version == null`）时，自动查找该 Ward 更早的非空 Thread 并返回 `previous_thread_id`，使客户端能无缝继续往上翻阅重绑前的历史记录。
  3. **客户端游标分页与视口分窗口虚拟化渲染（`duxue-app/lib/features/day_story_pages.dart`）**：
     - 将 `_HomeOverlay` 内的 `SingleChildScrollView` + `Column` 替换为带 `ScrollController` 的 `ListView.builder`，仅挂载当前可视窗口及缓冲区内的气泡 Widget；
     - 支持上滑到顶部自动触发（或点击顶部按钮触发）`_loadOlderMessages()`，按 `before_thread_version` / `previous_thread_id` 向前追加历史页，并在插入后补偿 `ScrollController` 偏移量以保持阅读视口稳定；
     - `_restoreCompanionThread()` 仅在服务端明确返回 `404` 时才重置本地 `companionThreadId` 并回退拉取 `current`，避免偶发网络错误冲掉本地会话。
