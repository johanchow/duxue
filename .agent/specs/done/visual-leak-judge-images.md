---
slug: visual-leak-judge-images
created: 2026-10-29T12:48:50Z
status: done
---

# visual-leak-judge-images spec

## 做什么 / 为什么
当 Ward 询问图片中自己已写作答是否正确时，让独立泄露裁判在需要判定答案边界的那一刻查看同一批已授权图片。当前裁判只有文本历史，无法区分“核验孩子已提交的作答”和“直接代做”，因而会把前者误判为 `final_answer` 并降级。不能为所有图片建立题图结构化流程：非题目图片仍只进入主模型，不新增视觉裁判调用。

## 验收标准
- [x] 只有候选已进入受保护的作业成果泄露检查、且本轮/可见窗口有已授权图片时，文字泄露裁判才收到图片；非作业图片和无图片轮次保持现有调用与行为。
- [x] 视觉裁判和文本裁判仍是同一个 fail-closed 结论：裁判能依据图片确认孩子已提交的计算/问答作答时，可放行准确确认或纠错；仅有题面、图片模糊或裁判异常时，仍不得放行最终答案。
- [x] 图片仅从已授权的当前附件与同一线程可见窗口取得，以 data URL 传给模型；不把图像字节写入 Langfuse/Grafana，且不新增图片 OCR、摘要、持久化或跨线程读取。
- [x] 主模型、泄露后重试和备用模型产生的候选均使用同一批裁判图片；现有图形（`visual`）泄露检查行为不变。
- [x] 覆盖端口/适配器、循环和工作流同构测试；相关服务端测试全绿并完成离线评测样本扩充或说明其不适用。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/application/workflows/tutor_turn.py`：将仅供文字泄露裁判查看的 `judge_images` 加入端口契约，不赋予候选或主模型任何绕过权限。
  - `duxue-server/app/application/workflows/tutor_loop.py`：只在既有 `needs_leak_check` 分支向文字裁判传入图片；重试和备用分支通过同一函数自然复用。
  - `duxue-server/app/application/workflows/tutoring_workflow.py`：从已缓存、已授权的当前图片与可见窗口图片组装 `judge_images`，并传入 `run_tutor_turn()`；不改主模型图片窗口。
  - `duxue-server/app/infrastructure/ai/tutor_turn_model.py`：使 `QwenLeakJudge` 将图片作为同一次多模态裁判调用的用户内容发送；保留无图时完全相同的文本调用。
  - 测试 fakes、unit/application/integration 测试、`docs/technical/domain-tutoring.md` 与 `.agent/notes/`：锁定授权范围、按需调用、fail-closed 与观测脱敏边界。
- 测试计划：
  1. 先为循环补红测：受保护且有图片时 judge 接收图片；无图和未触发泄露检查时不接收。
  2. 为工作流补红测：当前附件与可见窗口图片均可传入；其他线程或未授权对象不可进入。
  3. 为 `QwenLeakJudge` 补适配器测试：有图走多模态 payload、无图保持字符串 payload，并检查遥测净化不记录 data URL。
  4. 扩充首图边界离线样本，覆盖“孩子已写答案的图片核验”与“仅有题面”；运行针对性测试、服务端全量测试及 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 扩展裁判端口、循环与图片授权装配
- [x] 多模态裁判适配器与遥测脱敏
- [x] 单元、应用、集成与离线评测验证
- [x] 文档、决策笔记、diff review
- [x] 图片核验场景的真实原图离线裁判用例

## 备注
- 视觉裁判组件使用 `tutoring.leak-judge@v8` / `qwen3.8-flash`：它与主答疑模型独立，并在当前兼容接口上完成了真实图片用例 3 次有效裁决（均为 `leaks=false`）。
- 后续多图目标规则已收窄图片输入：主调用和裁判使用同一批已选定的目标图，详见 `resolve-multiphoto-reference`。
