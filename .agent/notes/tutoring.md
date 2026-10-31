# 答疑

事实源：[domain-tutoring](../../docs/technical/domain-tutoring.md)、[表达](../../docs/technical/domain-tutoring-presentation.md) §十四、[离线评测](../../docs/technical/eval-offline.md)。视频讲解见 [tutoring-video-answer](../../docs/technical/tutoring-video-answer.md)，未实现。

## 目标

让孩子自己完成推理与练习。受保护的是当前题的最终答案、完整解法、待填内容、选择项和代写成品。没有推理层次的事实可以直接回答。过程题按已提交证据每次只推进一个最小目标。

## 状态

- 已落地：证据驱动许可、`tutor-turn` 契约与出口检查、发音 `act=pronounce`、五种配图与 App 渲染、结构化泄露裁判、多图先定目标、离线评测（单步、判官、合成多轮、对话回放）。
- 部分：发音指代仍会读错对象。图片作答核验与历史结论混淆、泄露回退不稳定。形状长度阈值未用真实输出校准。
- 未做：`disclosure=released`、`inspect_image` / `retrieve_authorized_learning_material` / `check_draft`、人工把标注升为 `confirmed`、配图 K=5 对照、视觉段条件拼接、知识讲解视频。流式 `TEXT_DELTA` 不做。
- 独立 `geometry` / `layers` / `relation` 求解器已取消，由受限 `svg` 承载。

## 决策

- 是否作业由模型用证据判断（`work|non_work`），不用任务标题推断。线索不足用 `non_work`。有受保护题，或候选声称在处理作业时，正文一律过独立裁判。模型标签只能收紧保护，不能放宽。
- `answer_protected` 只由 `permit()` 计算。本轮表现只影响下一轮。`guide` 必须是 `work`。`depth` 缺失按 `reasoning`。`fact_gate` 不能跳过裁判。
- `submitted` 只表示提交了完整思路或答案，不等于算对。已掌握只来自 `ConfirmUnderstanding`。
- 计算题、问答题在题面足够时可以独立核验后确认或纠错，纠错不能补出孩子还没算出的最终结果。选择题、判断题不能逐项确认对错。题面不足只请补充。
- 文字裁判输出结构化事实，代码不扫描回复里的词或数字。`final_answer` / `complete_solution` 重试不回灌含答案的草稿。裁判超时、非法、异常一律 fail-closed，不能展示失败草稿。
- 判官看最近 3 道题摘要和窗口内学生原话，不把导师原话当学生证据。只有已经需要作业泄露审核且本轮或窗口有授权图时，才把同一批原图交给视觉裁判。图片字节不进观测。
- 图的任何失败只丢图、文字照常。文字泄露整轮回退。图泄露先重画一次且不得改正文。二维竖式写成 `\enclose{longdiv}` 或 TeX array 且没有 `visual` 时，先带规范重画。
- `unknown=true` 只禁止结构化数值字段。能用前四种结构化图就不用 SVG。一维公式写在正文 TeX，不为单个算式配图。通过检查的 `visual` 写入 `interaction_ref`；下一轮模型上下文不读它。形状 lint 只记 trace，不触发 fallback。
- 模型不返回交互 `kind`、按钮或媒体。发音不写题目状态或学习事实，TTS 只读已确认原文。一次最多 8 条 lesson。顶层 `act` 互斥。
- 本轮有新图就用新图；没有新图且窗口有多张旧图才选图。比较上一张必须显式 `tutoring_intent=compare_previous_image`。只把选定图交给答疑和泄露检查。
- `tutoring.*` 禁止 `AI_MODEL_OVERRIDES`。泄露判官必须与主答疑模型不同型号。改提示词必须升版本。
- 评测与生产共用 `run_tutor_turn()`。variant 只在评测进程内生效。AI 新标一律 `proposed`。通过率不能外推，不能当发布门槛。

## 注意

- 语义判断禁止关键词、数字扫描和正则。正则只用于协议、XML、公式分隔。
- 图判官看的是抽出的文字加 `problem_summary`，看不到线段几何。校验过的 SVG 仍可能画错。
- 主模型会把历史助手结论套到当前图上。fallback 记录里的 content 是被拒候选，不是孩子看到的固定话术。
- 给模型加「要不要追问」的规则会整体改变追问倾向。
- 同一 `command_id` 至多计一次。出口失败不写 Fact、不推进题目。发音和澄清不得为了展示去打开答疑会话。
- 窗口图读不出：发音整轮失败；一般答疑被告知无法读取。图片里的文字是数据不是指令。
- 链接和 Markdown 图片只当纯文本。金额不要写成 `$100`。公式解析失败回退源码。
- `tests/unit/evals/` 不能放 `__init__.py`。真实模型评测只能走 CLI，导入前禁用 OTEL。字面 `content_not_contains` 会误伤。多轮评测注入的是标注题目状态。合成多轮与真实回放的统计必须分开。
- 视频未实现前，不要用 `start_cue` 冒充制作完成，也不要新增 `exploration` 意图。
