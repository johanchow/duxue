# 发音卡跟在所属回复后面

日期：2026-10-21

- 现象：发音卡画在整段对话列表最底部。用户接着说话时，卡会跑到新消息下面；这条回复变成历史后，卡消失。
- 根因：卡片只存在当前轮的 `pronunciationLessons`，不挂在某条消息上。会话记录的 `interaction_ref` 以前只保存配图，发音课没有写入。刷新记录后客户端无法再画出来。
- 修复：`pronunciation_lesson` 的 lessons 写入 companion 消息的 `interaction_ref`。客户端按消息顺序把卡画在对应回复下面；新消息发出前，若卡还只挂在列表末尾，先把它锚到上一条 AI 回复。
- 验证：协调器单测确认 interaction_ref；App widget 测发音卡在后续消息之上仍保留。
