# 发音辅导接到现有答疑入口

日期：2026-10-07

`pronunciation-guidance.v1` 从 `TutoringWorkflow` 进入，条件是本轮 `tutoring_intent=pronunciation`。它不打开 `StudySession` / `TutoringSession`，也不写 Outbox。

- 教学卡表 `pronunciation_lessons`，幂等键 `run_id + turn_id + attempt`。迁移 `20261007_22`。
- 读取：`GET /pronunciation-lessons/{lesson_ref}` 与 `GET /pronunciation-lessons/{lesson_ref}/speech?rate=`。
- 阿里云标准 TTS 只收教学卡上的原文。音色登记为 `en-US=betty`、`en-GB=emily`。`0.5/0.75/1.0` 对应 `speech_rate` `-500/-167/0`。超过 300 字不调用供应商。
- Token 复用 OSS AccessKey，Appkey 用 `TTS_APPKEY`。未配置或超时时接口返回 `tts_error`，教学卡仍在。
- 物理表与内存缓存策略已写入 `design-server.md`。删 Ward 时删除 `pronunciation_lessons`。音频不落盘。
- App 在孩子首页对话里用「读出发音」显式带上 `tutoring_intent=pronunciation`。教学卡默认不自动播放；点播放后按所选倍速取 MP3，服务端失败则改用手机朗读原文。
