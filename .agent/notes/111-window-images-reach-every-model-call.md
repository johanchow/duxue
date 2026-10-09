# 对话窗口的图片进入每条模型调用

日期：2026-10-08

事实源：`docs/technical/domain-companion.md` §1.1 窗口规则；答疑与发音只在 `domain-study.md` 链到它。

- 问题：窗口只给模型 `had_image` 标记，答疑、意图、题型、历史命中、复盘和计划审阅提示都看不到图，却被暗示"有图"。
- 决定：去掉 `had_image`。窗口行带 `image_urls`（已授权 data URL）；`utterance_window.user_content` / `image_parts` 把图编号后和 JSON 文本放进同一条用户消息，文本只有 `image_ids` / `current_image_ids`。路径和 base64 不进文本；`instruction_with_window` 只写编号。
- 读取规则在 `run_transcript.visible_utterances`：只读当前 Ward 前缀的 key，最近 8 张，读不出来是 `None`，模型被告知「无法读取」。发音用 `strict=True`，窗口图读不出来整轮失败。只有图、没有文字的原句也留在窗口。
- 各端口新增 `current_images`（本轮图）；`QwenAgentModelGateway.generate` 增加 `recent_utterances` / `current_images`。测试里的 fake 需要同样接受它们。
- 坑：`Settings` 是 frozen dataclass，测试要换模块里的 `settings` 引用。`test_e2e::test_ward_can_pause_and_complete_planned_or_unplanned_tasks` 在本改动前已失败，与本事无关。
- 未做：监护人侧 `task_intake` 不读 Ward 窗口，不在范围内。图片会让每次小调用的 token 变多，需要看用量后再决定是否把意图分类降成只读最近几张。
