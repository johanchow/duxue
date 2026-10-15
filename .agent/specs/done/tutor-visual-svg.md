---
slug: tutor-visual-svg
created: 2026-10-14T15:19:57Z
status: done
---

# tutor-visual-svg spec

## 做什么 / 为什么
在现有第一层 Flutter 原生结构化配图（`steps`、`compare`、`segment`、`number_line`）之上，新增第二层 **`flutter_svg` 受限矢量图通道（`kind="svg"`）**（方式 B：模型直出受限静态 SVG + 本地确定性校验/清洗 + `flutter_svg` 渲染），不引入通用 HTML/Mermaid WebView。

动机：
1. 固定 JSON 图型只能覆盖线性步骤、对比表、线段图和数轴；平面几何、空间/包含结构、有向关系图、物理/生物/地理原理示意等高频讲解场景需要自由矢量表达力。
2. 参照 WorkBuddy（`docs/diagram-and-show-widget-pipeline.md`、`docs/draw-02-how.md`、`docs/draw-03-check.md`、`z-presentation-kit/`）的 680px 固定画布与本地静态校验，可以在**零额外 LLM 调用**下完成 SVG 校验与主题适配。
3. 作业题同样允许使用 `kind="svg"`：通过提取 SVG 内所有可见文本（`<title>`、`<desc>`、`<text>`、`<tspan>`）进入 `describe(visual)`，复用现有的答案标记检查、并行 `visual-leak-judge` 判官与独立输出安全审核。

## 验收标准
服务端契约与本地校验（`duxue-server`）
- [x] `tutor_visual.py` 新增 `SvgVisual(kind="svg", alt=..., title=..., svg=...)`，并入 `Visual` 判别联合。
- [x] `SvgVisual` 本地确定性校验（不调 LLM，耗时 <1ms，违反任一条则整张丢弃并记 `visual_invalid`）：
  - 根标签必须是唯一 `<svg>`，不含 `<!DOCTYPE`、`<html>`、`<head>`、`<body>`、注释；
  - `viewBox` 必须为 `"0 0 680 H"`（`680` 固定宽度，`40 <= H <= 1600`）；
  - XML 可由标准库安全解析（拒绝实体扩展 `<!ENTITY`），且元素总数有上限（≤ 120 个节点，代码长度 ≤ 16,000 字符）；
  - 严格标签白名单：`svg`、`defs`、`marker`、`g`、`rect`、`circle`、`ellipse`、`line`、`polyline`、`polygon`、`path`、`text`、`tspan`、`title`、`desc`、`linearGradient`、`stop`（禁止 `script`、`foreignObject`、`image`、`a`、`iframe`、`style`、`form` 等）；
  - 严格属性检查：禁止任何 `on*` 事件属性、`href` / `xlink:href` 外链、`url(http...)`、`<11px` 的字号；
  - 规范化修复：作为连接器的 `<path>` / `<polyline>` 若未显式设置 `fill`，或带 `marker-end` / `marker-start` 却未设 `fill="none"`，自动补 `fill="none"`；根节点确保 `width="100%"`。
- [x] `describe(visual)` 支持 `SvgVisual`：提取 `title`、`alt` 以及 SVG 树内 `<title>`、`<desc>`、`<text>`、`<tspan>` 的全部可见文字，供答案标记检查、`visual-leak-judge`（作业防泄露）和 `SafetyScreeningPort`（输出安全审核）使用。
- [x] 作业题轮次（`answer_protected=true`）不禁用 `kind="svg"`：与现有 4 种图型一样，通过 `describe(visual)` 走答案标记 + 并行 `visual-leak-judge`，判泄露或判官失败时**只丢图、文字照常展示**。
- [x] 系统提示词升版（`tutoring.turn.system.v12` / 组件 `tutoring.turn@v12`）：
  - 明确两层画图分工：优先用 `steps`/`compare`/`segment`/`number_line`；当这四种无法表达（几何图形、层级包含、多分支关系、学科原理示意）时用 `kind="svg"`；
  - 注入精简版 680 画布规范（`viewBox="0 0 680 H"`、安全区 `40..640`、连接线 `fill="none"`、显式 `fill` 或 `var(--color-*)`、字号 ≥11px、作业题待求量标 `?` 不写答案）；
  - 更新 `test_prompt_lock.py` 与 `test_tutor_visual.py` 的提示词契约校验。

客户端渲染与主题适配（`duxue-app`）
- [x] `duxue-app/pubspec.yaml` 引入 `flutter_svg`。
- [x] `VisualBlock`（`lib/features/visual_block.dart`）新增 `SvgData` 分支（`kind == 'svg'`）：
  - 客户端二次防御校验（非空、`<svg` 开头、无 `<script` / `on*` / `foreignObject`、解析 `viewBox="0 0 680 H"`）；
  - 主题色摊平函数（参考 `materializeShowWidgetSvgTheme`）：将 `var(--color-text-*)`、`var(--color-background-*)`、`var(--color-border-*)` 及深浅色色阶替换为当前 Flutter `ThemeData.colorScheme` 对应的十六进制颜色，确保浅色/深色模式下均清晰可读；
  - 使用 `SvgPicture.string` 按 `680 : H` 宽高比自适应容器宽度渲染（高度上限保护），解析异常降级为空组件、不抛错；
  - 无障碍：`Semantics` 暴露 `alt` 与提取出的 `<text>` 文本。

测试与文档同步
- [x] 服务端单元测试覆盖 `SvgVisual` 合法样例、各类非法/越权/XSS 拦截、连接器 `fill="none"` 规范化、`describe(SvgVisual)` 文本提取、作业防泄露判官放行与丢图。
- [x] App 端 `visual_block_test.dart` 覆盖 `kind="svg"` 在浅色/深色/窄屏/大字号下的渲染、CSS 变量替换、无障碍标签及非法 SVG 静默降级。
- [x] 同步更新 `docs/technical/domain-tutoring-presentation.md`、`docs/technical/domain-tutoring.md`、`docs/technical/design-app.md`，记录决策到 `.agent/notes/`。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/application/workflows/tutor_visual.py`（新增 `SvgVisual`、XML 安全校验与清洗、`describe` 扩展）
  - `duxue-server/app/infrastructure/ai/prompts.py`、`components.py`（升版 `tutoring.turn.system.v12`）
  - `duxue-server/tests/unit/tutoring/test_tutor_visual.py`、`test_visual_vetting.py`、`tests/unit/ai/test_prompt_lock.py`
  - `duxue-app/pubspec.yaml`（添加 `flutter_svg`）
  - `duxue-app/lib/features/visual_block.dart`（新增 `SvgData`、CSS 变量主题摊平、`_SvgView`）
  - `duxue-app/test/visual_block_test.dart`（新增 SVG 渲染、深浅色主题、非法降级测试）
  - `docs/technical/domain-tutoring-presentation.md`、`docs/technical/domain-tutoring.md`、`docs/technical/design-app.md`
- 测试计划：
  - `pytest tests/unit/tutoring/ tests/application/study/test_tutoring_visual_projection.py tests/unit/ai/test_prompt_lock.py`
  - `flutter test test/visual_block_test.dart` 与 `flutter analyze`

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 搭脚手架
- [x] 步骤 1：服务端 `SvgVisual` 契约、本地 XML 校验/规范化与 `describe` 文本提取 + 单测
- [x] 步骤 2：主模型提示词升版 `v12`（加入 `kind="svg"` 规范与示例）+ prompt lock 测试
- [x] 步骤 3：App 端引入 `flutter_svg`，实现 `SvgData` 解析、主题变量摊平与 `_SvgView` 渲染 + widget 测试
- [x] 步骤 4：同步技术文档与 `.agent/notes/`，全量相关测试与 `git diff --check`

## 备注
- 遵循“方案简单”原则：包含两层渲染能力（第 1 层 Flutter 原生 `steps`/`compare`/`segment`/`number_line` + 第 2 层 `flutter_svg` 受限矢量图 `svg`），不引入 WebView。
