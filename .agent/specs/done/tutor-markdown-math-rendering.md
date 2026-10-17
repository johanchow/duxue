---
slug: tutor-markdown-math-rendering
created: 2026-10-17T11:11:45Z
status: done
---

# tutor-markdown-math-rendering spec

## 做什么 / 为什么
参照 `docs/assistant-markdown-body-contract.md`，在读学答疑（`domain-tutoring.md` / `domain-tutoring-presentation.md`）中补齐**助手正文 Markdown 与 TeX 公式契约、形状检查与客户端原生渲染**：
1. **双轨分工**：算式、分式、方程、科学式用 TeX（`$...$` / `$$...$$` / `\(...\)` / `\[...\]`）直接写在 `TutorTurnCandidate.content` 字符串中，客户端走 `flutter_math_fork`（`Math.tex`）原生渲染，**不为公式调配图或引入 WebView**；流程图、对比表、线段图、数轴、几何与结构示意图继续走现有的两层 `VisualBlock`（第 1 层 Flutter 原生 4 图型 + 第 2 层 `flutter_svg` 受限静态 SVG）。
2. **服务端提示词与形状 Lint**：在 `tutoring.turn` 系统提示词中明确公式与 Markdown 契约（分式 `\frac{a}{b}`、根号 `\sqrt{}`、方程组 `cases`/`aligned`，金额用“100 元”不用 `$100`，不用 Unicode 假公式或图片）；升级 `tutor_shape.py`，对 `<br>`/`<br/>` 不误判为 `raw_html`，并覆盖未闭合 `$$` 与 `\(...\)`/`\[...\]` 的公式配对检查。
3. **客户端安全 GFM + TeX 渲染**：在 `duxue-app` 新增伴学气泡专用的 `AssistantMarkdownBody`（或 `TutorMarkdownBody`）组件，支持 GFM 常用语法 + 4 项容错扩展（单换行转真换行 `softLineBreak`、严格 `~~` 删除线防止 `1~10` 被划掉、宽松 `**粗体**` 兼容中文标点、`<br>` 换行）+ 行内/块级 TeX 公式渲染（块级横滑、解析失败回退显示源码）+ **未成年人安全护栏**（禁用外链跳转、自动 URL 与 Markdown 内联图片 `![](...)`，标题字号压平贴近正文），并接入 `_ChatBubble`。

## 验收标准
服务端契约、提示词与形状 Lint（`duxue-server`）
- [x] `prompts.py` 升版 `tutoring.turn.system.v13`（及 `components.py` 中 `tutoring.turn@v13`）：明确正文公式书写规范（行内 `$...$`、独立方程 `$$...$$`、分式 `\frac{a}{b}`、根号 `\sqrt{}`、方程组 `cases`/`aligned`；金额写“100 元”不写 `$100`；不为单个算式生成 `visual`）；`test_prompt_lock.py` 同步通过。
- [x] `tutor_shape.py` 升级：
  - `<br>` / `<br/>` / `<br />` 视作合法换行容错，不触发 `raw_html`；其它 HTML 标签仍记 `raw_html`；
  - 公式分隔符配对检查：除行内单 `$` 外，覆盖未闭合 `$$` 以及未配对的 `\(` / `\)`、`\[` / `\]`（统一记 `unpaired_dollar`，保持低基数观测标签稳定），忽略代码块内的 `$`；
  - 形状 lint 保持只读、只记录，绝不触发 fallback。

客户端 Markdown + TeX 渲染（`duxue-app`）
- [x] `duxue-app/pubspec.yaml` 引入 `flutter_math_fork` 与 `markdown`（纯 Dart AST 解析 + 自定义行内/块级 Builder，无需引入已停更的 `flutter_markdown` 或重量级 `flutter_highlight`）。
- [x] 新增 `lib/shared/chat_markdown.dart`（`ChatMarkdownBody`）：
  - **GFM 与容错扩展**：段落、加粗/斜体、有序/无序列表、引用块、等宽代码、紧凑横滑管道表格；单个 `\n` 渲染为换行；`<br>` / `<br/>` 转为换行；严格删除线只认 `~~`（`1~10` 不变成删除线）；宽松 `**粗体**` 容错（兼容 `**内容 **` 与中文全角括号边界）；标题 H1–H6 压平为加粗且字号贴近正文，不撑破气泡；
  - **TeX 公式渲染**：支持行内 `$...$`（单行、闭合、首尾无多余空白，不满足则保留 `$` 原文）与 `\(...\)` 走 `Math.tex(..., mathStyle: MathStyle.text)` 嵌进 `WidgetSpan`；支持块级 `$$...$$` 与 `\[...\]` 走 `Math.tex(..., mathStyle: MathStyle.display)` 并外包横向 `SingleChildScrollView`；未闭合围栏或 KaTeX 解析异常时通过 `onErrorFallback` 安全回退为纯文本源码，不抛异常、不空白；
  - **未成年人安全红线**：Markdown 内联图片 `![alt](url)`、链接 `[text](url)` 与裸 URL 一律只渲染纯文本，**不发起任何网络图片请求、不触发外部链接跳转**；
  - 接入 `lib/features/day_story_pages.dart` 的 `_ChatBubble`（替换原有的裸 `Text(text)`）。

文档与测试
- [x] 服务端单元测试 `test_tutor_shape.py`、`test_tutor_visual.py`、`test_prompt_lock.py` 全绿。
- [x] 客户端新增 `test/chat_markdown_test.dart`：覆盖行内公式 `$...$` / `\(...\)`、块级公式 `$$...$$` 横滑、非法 TeX 降级为源码、`1~10` 不触发删除线、`~~删除~~` 生效、`<br>` 换行、宽松粗体、单换行保留、外链/图片不发起网络请求或跳转，以及深浅色与大字号渲染；`app_ui_test.dart` 与 `flutter analyze` 全绿。
- [x] 同步更新 `docs/technical/domain-tutoring.md`、`docs/technical/domain-tutoring-presentation.md`、`docs/technical/design-app.md`、`docs/technical/infra-ai-components.md`，并在 `.agent/notes/` 记录决策。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/infrastructure/ai/prompts.py`、`components.py`（升版 `tutoring.turn.system.v13` / `tutoring.turn@v13`）
  - `duxue-server/app/application/workflows/tutor_shape.py`（升级 `<br>` 容错与公式分隔符配对检查）
  - `duxue-server/tests/unit/tutoring/test_tutor_shape.py`、`tests/unit/ai/test_prompt_lock.py`
  - `duxue-app/pubspec.yaml`（添加 `markdown`、`flutter_math_fork`）
  - `duxue-app/lib/shared/chat_markdown.dart`（新建：AST 解析、4 项容错扩展、行内/块级 `Math.tex`、安全无外链/无外图 Widget 树构建）
  - `duxue-app/lib/features/day_story_pages.dart`（`_ChatBubble` 接入 `ChatMarkdownBody`）
  - `duxue-app/test/chat_markdown_test.dart`（新建）、`duxue-app/test/app_ui_test.dart`
  - `docs/technical/domain-tutoring.md`、`docs/technical/domain-tutoring-presentation.md`、`docs/technical/design-app.md`、`docs/technical/infra-ai-components.md`
  - `.agent/notes/126-tutor-markdown-math-rendering.md`
- 测试计划：
  - 服务端：`pytest tests/unit/tutoring/ tests/unit/ai/`
  - 客户端：`flutter test test/chat_markdown_test.dart test/visual_block_test.dart test/app_ui_test.dart` 与 `flutter analyze`

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 步骤 1：服务端 `tutor_shape.py` 升级与 `tutoring.turn.system.v13` 提示词升版 + 单测
- [x] 步骤 2：App 端引入 `markdown` + `flutter_math_fork`，实现 `ChatMarkdownBody` 并接入 `_ChatBubble` + widget 测试
- [x] 步骤 3：同步技术文档（`domain-tutoring.md` 等）与 `.agent/notes/`，跑全量相关测试与 `git diff --check`

## 备注
- 遵循“方案简单”原则：用纯 Dart 的 `package:markdown` + `flutter_math_fork` 直接构建伴学气泡所需的轻量 Widget 树，既避免已停更的 `flutter_markdown` 传递依赖冲突，又天然从根源阻断外链点击与外部图片加载。
