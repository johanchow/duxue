# 130 发音辅导支持词义同答与多词发音卡

日期：2026-10-18

事实源：`docs/technical/domain-tutoring.md` §4.1、§4.6。

- 起因：Grafana 线上日志（trace `535548621f37d866fc78449ea2a023a5` 等）显示，孩子问「start 是什么意思？怎么读？」「图上的所有单词什么意思？怎么读？」时，模型全部走了 `act="answer"` + `topic="atomic_lookup"`，只在文本里写音标，未触发 `pronunciation_lesson` 点读卡。
- 根因：
  1. `prompts.py` 原把「词义、字音、图里是什么」归入 `atomic` → `act=answer`；
  2. `project_lesson` 之前用 `lesson.introduction` 覆盖了气泡文本，丢弃了 `candidate.content`；
  3. `PronouncePayload` 仅支持单条 `lesson`，遇到「图上所有单词怎么读」无法承载多词。
- 改动：
  - **保持顶层 `act` 互斥不变量不变**（不把 `act="answer"` 带 `pronounce` 转正，防止绕过作业题泄露裁判）。
  - **Prompt（`tutoring.turn.system.v14` / `tutoring.turn@v14`）**：明确规定凡问外语单词或句子怎么读（含同时问「什么意思 + 怎么读」或一次问多个词怎么读），一律选 `act="pronounce"`；在 `content` 中写清中文意思，单条填 `pronounce.lesson`，多条（最多 8 个）填 `pronounce.lessons`。`atomic` 中的「字音」明确为「汉字读音」。
  - **契约与校验（`tutor_turn.py`）**：`PronouncePayload` 支持 `lesson` 或 `lessons`（1–8 条）并统一归一为 `lessons: list[LessonBody]`，保留 `candidate.lesson` 属性返回首条以兼容现有调用与评测；`check_authority` 逐条校验 `candidate.lessons`。
  - **投影与点读查询（`pronunciation_guidance.py` / `pronunciation_speech.py`）**：
    - `project_lesson` 使用 `candidate.content` 作为气泡正文（回退 `first.introduction`），使聊天气泡展示完整词义。
    - 多词复用同一行 `pronunciation_lessons`（免数据库迁移），首条 `speech_ref` 为 `{id}`，后续为 `{id}:{index}`；`PronunciationLessonQuery.get/speak` 解析 `{id}:{index}` 并按对应词条合成语音。
  - **App 端（`day_story_pages.dart`）**：从 `lesson['lessons']`（兼容单卡 `lesson`）渲染 1~N 张 `PronunciationLessonCard`，每张独立点读与调速。
  - **离线评测（`evals/`）**：`Expect` 新增 `lesson_source_contains_all` 与 `min_lessons` 断言，`Observation` 记录 `lesson_sources` 列表；在 `evals/data/tutoring_turn.jsonl` 新增会话 `4d43c20f` 的多词/单词「怎么读？什么意思？」回归用例（`turn-4d43c20f-00`、`turn-4d43c20f-01`）。
