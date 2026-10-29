---
slug: chat-history-image-viewer
created: 2026-10-29T15:30:37Z
status: done
---

# 历史对话图片全屏查看

## 做什么 / 为什么
Ward 点击聊天气泡中的图片后，能像微信聊天一样全屏查看、双指缩放、左右切换同一条消息的多张图片，并能返回聊天原位置。当前历史消息仅保存附件引用，重启 App 后图片会消失，因此一并补齐按需读取。

## 验收标准
- [x] 当前会话及跨 Thread 的历史消息均显示图片缩略图；重新打开 App 后仍可查看。仅为进入视口的图片按需读取，不因分页一次性下载整段历史。
- [x] 点击任意缩略图全屏打开对应图片；黑色背景、适屏显示、双指缩放与拖动，支持返回；同一条消息有多张图片时可左右切换，初始页为点击的图片。
- [x] 全屏使用原始已上传字节，不复用 72 像素缩略解码；放大或关闭后聊天位置和消息内容不变。
- [x] 服务端仅向当前 Ward 返回其可见消息引用的图片；无效消息、索引和跨 Ward 请求无法读取对象。
- [x] Flutter 交互测试与服务端授权测试通过，相关测试全绿。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/api/v1/companion.py`：按消息 ID 和附件序号提供带 Ward 身份校验的图片读取接口；检查附件键的 Ward 前缀与图片类型。
  - `duxue-app/lib/core/api_client.dart`：增加读取单张历史消息图片的接口。
  - `duxue-app/lib/features/day_story_pages.dart`：保留消息的附件引用，在缩略图进入列表视口时按需读取并缓存；点击缩略图打开全屏查看器。
  - `duxue-app/lib/features/chat_image_viewer.dart`：全屏适屏查看、缩放/拖动、多图翻页及退出交互。
  - `duxue-app/test/app_ui_test.dart` 与服务端 companion API 测试：覆盖历史恢复、点击与翻页、授权拒绝。
  - `docs/technical/domain-companion.md`、`docs/technical/design-app.md`：记录历史图片读取与显示边界。
  - `.agent/notes/`：记录按需读取和全屏展示的设计取舍。
- 实施顺序：先写授权/交互复现测试，再补最小接口与界面实现，完成测试和 diff review。
- 测试计划：运行受影响的 Flutter widget tests、服务端 companion API tests，并检查 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 确认现有图片上传、消息引用与历史展示链路
- [x] 制定验收标准、影响文件和测试计划
- [x] 先补失败测试
- [x] 增加受控历史图片读取与 App 按需加载
- [x] 完成全屏缩放、多图切换和返回交互
- [x] 运行测试、复核 diff、沉淀笔记并提交验收

## 备注
按用户明确要求，本次提交一并纳入 `.cursor/skills` 的子模块索引更新。
验收前验证：Flutter `app_ui_test.dart` 38 项通过；服务端 companion use case + E2E 共 27 项通过；受影响 Flutter 文件 `flutter analyze` 无问题；`git diff --check` 通过。
