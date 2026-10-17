# 126 — 答疑正文 Markdown 与 TeX 公式渲染（`ChatMarkdownBody`）

- spec: `.agent/specs/tutor-markdown-math-rendering.md`
- 设计文档：`docs/technical/domain-tutoring.md`、`docs/technical/domain-tutoring-presentation.md`、`docs/technical/design-app.md`、`docs/technical/infra-ai-components.md`、`docs/assistant-markdown-body-contract.md`

## 决策记录

1. **正文（Markdown + TeX）与配图（2 层 `VisualBlock`）双轨分工**
   - 算式、分式（`\frac{a}{b}`）、根号（`\sqrt{}`）、对齐推导（`aligned`）、方程组（`cases`）一律作为 UTF-8 Markdown + TeX 字符串直接写在 `TutorTurnCandidate.content` 中，由客户端 `flutter_math_fork`（`Math.tex`）原生渲染，**不为单个算式生成 `visual` 配图，也不引入第 3 层 WebView**。
   - 配图维持 2 层架构：第 1 层 Flutter 原生结构化图（`steps`、`compare`、`segment`、`number_line`）；第 2 层 `flutter_svg` 受限静态矢量图（`kind="svg"`）。

2. **纯 Dart `package:markdown` + `flutter_math_fork` 自建 `ChatMarkdownBody`，不引入 `flutter_markdown`**
   - `flutter_markdown` 已停更且拉入不必要的传递依赖；伴学气泡只需受控 GFM 子集与公式混排。
   - 直接用 `package:markdown` 构建 AST 并映射为 Flutter `Text.rich` / `Table` / `Math.tex` 组件树：
     - 纯文本单段退化为标准 `Text`，带行内公式或样式的段落使用 `Text.rich`，保证 Flutter Test 的 `find.text(...)` 无需改写即可匹配。
     - **行内语法优先级踩坑**：`md.EscapeSyntax()` 会吞掉 `\(` 与 `\[` 的反斜杠导致括号公式失效。因此在 `inlineSyntaxes` 中必须按 `CodeSyntax` → `_DisplayBracketMathInlineSyntax`（`\[...\]`）→ `_InlineParenMathSyntax`（`\(...\)`）→ `EscapeSyntax`（处理 `\$`、`\*`）→ `_DisplayDollarMathInlineSyntax`（`$$...$$`）→ `_InlineDollarMathSyntax`（`$...$`）的顺序注册。

3. **4 项生成式容错扩展与公式回退**
   - **严格删除线**：只认双波浪线 `~~...~~`，不认单波浪线 `~`，防止中小学数学常见的 `1~10` 区间被渲染成删除线。
   - **宽松 `**粗体**`**：兼容 `**内容 **` 尾部空格及中文全角标点相邻边界（如 `这是**（一）已知条件**`）。
   - **换行保真**：段落内单换行 `\n` 保留为真换行（`softLineBreak`），`<br>` / `<br/>` / `<br />` 转为真换行；服务端 `tutor_shape.py` 同步放行 `<br>` 不报 `raw_html`。
   - **公式安全回退**：行内 `$...$` 要求单行闭合、首尾无空格且闭合 `$` 后不紧跟数字（否则保留原 `$` 文本）；块级 `$$...$$` 与 `\[...\]` 外包横向 `SingleChildScrollView`；未闭合围栏或 KaTeX 解析异常通过 `onErrorFallback` 回退为纯文本源码展示，不崩溃、不空白。

4. **未成年人安全边界**
   - 禁用 `Autolink`；`[text](url)` 与 `![alt](url)` 仅提取可读文字按纯文本渲染，不绑定 `GestureRecognizer` 外链跳转，也不调用 `Image.network` 拉取外部图片。
   - 标题 H1–H6 压平为加粗、字号贴近正文，避免撑破伴学气泡。

5. **真实问答踩坑修复：解释原理类问题必须分步拆解并主动配图**
   - 线上 Grafana Loki 与审计日志（`trace_id=fcbe2bae9f54ca23ec913a7664fc0af0`，提问“说明一下地球的一年四季为什么会出现？”）发现：原提示词写“因果用连贯的句子讲，不用列表拆碎；answer 先给结论，再说一句原因”，且正例全是一句话纯文本，导致模型输出一整段无换行、无加粗的纯文本，也未主动附 `visual`。
   - 修复：
     1. `prompts.py`（`tutoring.turn.system.v13`）区分单句查询与原理解释：`answer` 解释“为什么、怎么形成、有什么区别”时，要求先用一句话给核心结论（`**粗体**` 标关键概念），再换行（`\n`）把有逻辑分步、先后过程或多层原因拆成 2–4 个小步说明（`1. **小步名**：简短说明`），并补充带 `**粗体**` + 分步编号 + `visual` 的水循环正例；同时强化原理解释类问题主动附 `visual`（不必等孩子点名要图）。
     2. `tutor_shape.py` 中 `list_heavy` 对 `act="answer"` 仅统计无序圆点列表（`_BULLET_LINE`），放行有逻辑先后顺序的编号小步（`1. 2. 3.`），而 `act="guide"` 仍对编号和圆点列表均统计以防替孩子列出完整解题步骤。
