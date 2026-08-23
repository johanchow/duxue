# 实时按住说话转文字

- 传递输入栏使用 `record 6.2.1`，而非最新 7.x：仓库当前 Dart 3.8.1，而 7.x 需要 Dart 3.12；6.2.1 同样支持 PCM16 流。
- Flutter 将 `PCM16 / 16kHz / 单声道` 音频通过自身 JWT WebSocket 发送到 `/ws/asr/transcribe`。App 永不持有百炼 Key；服务端先校验所有选中 Ward 的 `guardian_ward_relations`，才连接百炼。
- 百炼代理采用 `qwen3-asr-flash-realtime` 的 Manual 模式：实时 `partial` 文本更新输入框，松手提交 commit 后以 `final` 回填；原始音频不落盘，最终文本仍要由 Guardian 点击发送。
- 输入栏左右 padding 缩至 12px，仅保留 44px 麦克风和附件触控区，移除额外占位，让多行文字框使用剩余宽度。
- 验证：后端 pytest 22 项通过（含 Guardian WebSocket 的 partial/final 流测试）；`flutter analyze` 通过，Flutter 测试 6 项通过。真实百炼调用须由部署环境填写 ASR 变量后进行，不使用真实 Key 的本地测试不访问外部服务。
