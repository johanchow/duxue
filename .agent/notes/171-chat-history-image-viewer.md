# 历史对话图片按需读取与全屏查看

日期：2026-10-29

事实源：[历史对话图片全屏查看 spec](../specs/done/chat-history-image-viewer.md)；接口与客户端行为见 [`domain-companion.md` §5.1](../../docs/technical/domain-companion.md#51-ward-facing-transcript-journal) 和 [`design-app.md` §3.1](../../docs/technical/design-app.md#31-伴学答疑引擎sse-流式解析与-latex-混排)。

- 之前 `rememberedImages` 只保存当前进程上传的字节，重启后 transcript 仅有 `attachment_refs`，图片气泡消失。客户端现在保留引用，列表视口构建缩略图时从消息附件接口读取，并在页面内缓存最多 48 张；不随着历史分页一次性下载全部图片。
- 服务端以消息 ID 和序号定位附件，校验消息属于当前 Ward、作者是 Ward、对象键仍在该 Ward 的 Companion 目录且无路径穿越，然后读取对象；不提供按任意对象键直接下载的接口。
- 全屏页使用原始上传字节，缩略图继续限制解码尺寸。`PageView` 在同一消息内翻页，`InteractiveViewer` 负责缩放和拖动，关闭后原聊天列表仍在原位。
- 相关测试：Flutter `app_ui_test.dart`、服务端 companion use case 和 E2E 的附件授权断言。
