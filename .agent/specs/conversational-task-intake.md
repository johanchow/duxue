---
slug: conversational-task-intake
created: 2026-08-23T06:36:24Z
status: draft
---

# conversational-task-intake spec

## 做什么 / 为什么
把 Guardian 的「传递给孩子」改成单一对话入口：Guardian 用文字、实时语音转写后的文字或图片描述事项；LLM 从当前 Guardian 已绑定的 Ward 中整理候选任务、追问含糊归属；Guardian 只在任务清单完整时一次性确认写入任务池。候选任务只保存于当前 App 底部弹窗状态，不落数据库。

## 验收标准
- [x] 「传递给孩子」不再预先选择 Ward；对话输入支持文字、现有按住说话转写和图片附件，语音最终文本须由 Guardian 点击发送为一条对话消息。
- [x] 每条对话消息经服务端 LLM 返回 assistant 文本及结构化的当前候选任务；App 按 Ward 分组展示只读任务清单，Guardian 只能继续以对话方式修正，不提供卡片直接编辑。
- [x] 服务端只允许从当前 Guardian 的 `guardian_ward_relations` 中分配 `ward_id`；多 Ward 情况下归属未被输入明确说明时，返回追问且 `ready_to_confirm=false`，不得默认复制或根据历史猜测。
- [x] 当所有候选任务的归属、标题均明确时才启用「确认传递」；确认请求携带结构化清单，服务端重新校验每项 Ward 关系并用一次事务创建 Assignment。取消/关闭对话不创建任务，也不持久化候选清单。
- [x] Guardian 图片只能上传到其临时任务输入路径，受类型、大小及 Guardian JWT 保护；图片能与文字一并交给模型解析，确认或取消后尝试清理临时文件，OSS 通过生命周期规则兜底清理。
- [x] LLM 输出采用服务端校验的 JSON schema，异常输出、模型不可用、图片上传失败和越权 Ward 均给出可恢复错误且不创建任务；后端与 Flutter 测试、`flutter analyze` 全绿。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/{main,schemas,config}.py`：增加 Guardian 专用临时附件上传、`/task-intake/respond` 对话解析和 `/task-intake/confirm` 原子提交 API；复用 Guardian/Ward 关系校验，不引入任务候选数据库表。
  - `duxue-server/app/task_intake.py`（新增）：封装 OpenAI-compatible 百炼调用与严格 Pydantic JSON 输出校验。系统 prompt 仅传入服务端查询到的 `{id, display_name, grade_stage}` Ward 白名单；要求任务归属不明时输出 `clarification_required`，禁止猜测、复制给多人或补造事实。模型配置新增可覆盖的 `TASK_INTAKE_MODEL`，默认复用当前百炼兼容配置。
  - `duxue-server/app/{storage,models}.py`（仅必要修改）：提供 Guardian 临时附件的受控 key、读取和删除能力；不保存 candidate/会话表。OSS 临时路径的生命周期规则作为部署配置说明。
  - `duxue-app/lib/features/ward_pages.dart`：用聊天气泡、只读“当前任务清单”、发送按钮和确认按钮重写现有底部弹窗；候选清单、聊天历史和附件 key 仅存在该弹窗 State。保留并接入现有实时 ASR，语音完成后回填输入框。
  - `duxue-app/lib/core/api_client.dart` 及新增轻量数据模型/图片选择依赖：请求解析、临时上传、确认与清理；附件菜单改为实际选择图片。
  - `.env.example`、后端/Flutter 测试及 `.agent/notes/`：说明模型参数与对象存储临时清理策略。
- 对话响应约定（先使用简单 JSON，不引入完整 AG-UI runtime）：`assistant_text`、`tasks`（每项含 `ward_id/title/details/due_date`）、`clarification_required`、`questions`、`ready_to_confirm`。这在 UI 上渲染为聊天气泡和结构化任务组件；后续需要多代理/工具调用时再兼容 AG-UI 事件流。
- 测试计划：后端 fake LLM 覆盖单/多 Ward 明确分配、模糊归属追问、非法/幻觉 Ward ID、确认越权、原子提交、LLM schema 错误和临时附件权限/清理；Flutter 覆盖聊天状态、语音回填后发送、图片消息、追问时确认按钮禁用、确认成功与关闭丢弃。最后运行 `pytest tests -v`、`flutter analyze`、`flutter test`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 服务端对话解析、临时附件和确认提交边界
- [x] Flutter 对话输入、图片与只读候选任务清单
- [x] Prompt/schema、防越权和异常路径测试
- [x] 全量验证与决策沉淀

## 备注
- 非目标：候选任务持久化、卡片点击编辑/拖拽、完整 AG-UI runtime、对话跨退出恢复。关闭弹窗即丢弃临时对话状态；只有确认后的 Assignment 是事实来源。
- Guardian 可以在对话中说“第二项给小雨”“把刚才的数学任务改到周五”；客户端发送当前对话历史和当前候选清单，服务端无状态地重新整理并返回更新后的清单。
