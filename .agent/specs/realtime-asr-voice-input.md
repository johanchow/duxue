---
slug: realtime-asr-voice-input
created: 2026-08-23T02:56:09Z
status: draft
---

# realtime-asr-voice-input spec

## 做什么 / 为什么
让 Guardian 在「传递给孩子」的微信式输入栏中按住麦克风说话，边说边看到临时识别文字；松开后由百炼实时 ASR 返回最终文本，仍须由用户确认发送任务。百炼 Key 只驻留在服务端。

## 验收标准
- [x] Flutter 输入栏两侧收窄至 12–16px，麦克风与附件各保留 40–44px 点击区，中间多行文字框占用其余宽度。
- [x] 长按麦克风可申请权限、采集 16 kHz / PCM16 / 单声道音频，并以约 100ms 的块流式发送；取消、权限拒绝、网络失败均有清晰且不创建任务的反馈。
- [x] 服务端 WebSocket 只允许 Guardian JWT 连接，开流前校验所选每个 `ward_id` 与 Guardian 的关系；百炼 API Key 永不下发到 App。
- [x] 服务端将临时 ASR 文本以 `partial` 消息实时转发、将最终文本以 `final` 消息转发；Manual 模式在松开时 commit，单次录音上限 60 秒。
- [x] 最终文本回填后可编辑；只有用户点「传递并待确认」才逐个为所选 Ward 创建文字任务；原始音频默认不持久化。
- [x] 后端 WebSocket/鉴权单测与 Flutter 交互/状态测试通过，`flutter analyze` 通过；补充 `.env.example` 配置说明和决策笔记。

## 实现计划（Gate 1：等待用户确认）

- 影响文件：
  - `duxue-server/app/{main,config,dependencies}.py`：增加 Guardian 鉴权的 ASR WebSocket 入口、按 Ward 关系校验、配置读取。
  - `duxue-server/app/asr.py`（新增）与 `requirements.txt`：实现到百炼 `qwen3-asr-flash-realtime` 的服务端 WebSocket 代理，使用 Manual 模式；只转发音频与文本，默认不落音频。
  - `duxue-server/.env.example`：增加 `ASR_API_KEY`、`ASR_MODEL`、`ASR_WORKSPACE_ID`、`ASR_REGION`、`ASR_MAX_RECORD_SECONDS` 的说明；实际秘密仅由用户填写 `.env` / `.env.prod`。
  - `duxue-app/pubspec.yaml`、原生 Android/iOS 麦克风权限文件、`lib/features/ward_pages.dart` 及新增语音服务：接入录音 PCM 流和 WebSocket，更新输入栏布局、长按状态及 partial/final 回填。
  - 后端/Flutter 测试与 `.agent/notes/`。
- 交互协议：App 先发 `start`（含多选 ward IDs），后连续发二进制 PCM 块，结束时发 `commit` 或 `cancel`；服务端回 `ready`、`partial`、`final`、`error`。App 不持有任何百炼凭据。
- 测试计划：服务端用假 ASR provider 覆盖身份、Ward 越权、partial/final/commit/error；Flutter 用 fake socket/recorder 覆盖按住、松开、取消、最终文本可编辑及文字任务发送；最后运行后端 pytest、Flutter analyze/test。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 服务端 ASR 配置、认证 WebSocket 与百炼代理
- [x] Flutter 录音流、实时文本状态与紧凑输入栏
- [x] 权限、错误状态与 60 秒保护
- [x] 测试、验证与决策沉淀

## 备注
