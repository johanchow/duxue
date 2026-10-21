# 137 — 数理化一维公式与二维对位 SVG 边界 + 移除语义正则/关键词检查

## 背景

1. **线上竖式案例（thread `ce40e94f-9c5e-486d-8f4c-71efaa8d0d62`）**：三年级学生在做加减法应用题时连续要求“竖式怎么写”“帮我列一个这个算式。竖式。”，模型连续 5 轮只返回纯文字引导，既不敢在 `content` 用字符画，又被提示词里的 `"单纯一个算式不要画成 visual"` 拦住不敢调 `widget_guidelines` 画 `svg`。
2. **脆弱的语义关键词/数字拦截**：出口检查中遗留了硬编码关键词 `ANSWER_LEAK_MARKERS = ("最终答案", "答案是", "所以选")` 以及 `tutor_visual.py` 中对 `unknown=true` 的 `label` 是否含阿拉伯数字的字符扫描 `_has_digit`。这类基于关键词/正则的语义猜测不可靠且易误杀正常表达（如 `"第1段"`、`"2倍"` 或引导句式）。

## 决策与改动

1. **铁律沉淀（`AGENTS.md` 铁律第 8 条）**：
   - 明确约定：**不要靠关键词列表、数字检测或正则表达式去检查语义化内容**（如答案泄露、意图理解、未知量文本描述）；正则与结构化校验只用于确定性的语法/协议格式，开放语义一律交由模型或独立 Judge 裁决。
2. **移除 `ANSWER_LEAK_MARKERS` 与 `_has_digit`**：
   - 删除 `app/contexts/study/domain/execution.py` 中的 `ANSWER_LEAK_MARKERS`，以及 `tutor_turn.py`、`tutor_loop.py` 中的 `answer_marker` / `visual_answer_marker` 分支；受保护轮次的正文（含 `clarify` 候选）与配图文字统一交由并行独立 Judge（`tutoring.leak-judge` / `tutoring.visual-leak-judge`）裁决。
   - 删除 `tutor_visual.py` 中的 `_has_digit`，`_unknown_has_no_value` 仅校验结构化数值字段（`value` / `at` / `start` / `end`）在 `unknown=true` 时必须为 `None`，与 App 端 `visual_block.dart` 保持完全一致。
3. **全学科公式与二维空间配图分工（`tutoring.turn@v17`、`tutoring.visual-leak-judge@v3`、`SVG_WIDGET_GUIDELINES`）**：
   - **一维常规公式走 `content`（LaTeX）**：算式、分式、根号、方程组、物理公式、化学方程式直接用 `$...$` / `$$...$$` 写在 `content` 中，不为单个一维算式画 `visual`。
   - **二维空间对位与结构式走 `visual (kind="svg")`**：需要二维空间对位、画线框或画结构的演算式与学科结构式（如数位对齐的竖式、几何与受力/电路图、化学分子或电子转移结构），以及孩子要求画出式子或图时，主动调用 `widget_guidelines` 并附 `kind="svg"`。
   - **作业题允许画 `?` 占位框架图**：`tutoring.turn@v17` 与 `tutoring.visual-leak-judge@v3` 同步明确，把已知数或符号按运算/结构对位摆成框架、但待求的数位/系数/边角/结果标为 `?`（或未知）的待填框架图，属于帮助审题与看清格式的引导，不算泄露答案。
   - **`SVG_WIDGET_GUIDELINES` 补充 `Aligned grid & spatial notation`**：规定固定列宽网格（`40..48px`、`text-anchor="middle"`）、运算符与分隔横线 `<line>`、以及未知位用高亮虚线框加 `?`。
