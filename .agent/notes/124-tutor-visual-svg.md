# 124 — 答疑配图第二层：`flutter_svg` 受限矢量图 (`kind="svg"`)

- spec: `.agent/specs/tutor-visual-svg.md`
- 设计文档：`docs/technical/domain-tutoring-presentation.md`、`docs/technical/domain-tutoring.md`、`docs/technical/design-app.md`

## 决策记录

1. **两层画图架构，不引入第三层通用 HTML/Mermaid WebView**
   - **第一层（Flutter 原生结构化图）**：`steps`、`compare`、`segment`、`number_line`。高频且结构固定，模型只传语义 JSON，客户端原生布局与绘制，零像素越界风险。
   - **第二层（受限静态矢量图 `kind="svg"`，方式 B）**：针对平面几何与辅助线、电路/受力、树形/环路/网格/自由概念图，由模型在同一次 `finish_turn` 中直接输出固定画布 `viewBox="0 0 680 H"` 的静态 SVG。无需二次 LLM 调用，也不再单独维护一套复杂的客户端几何约束求解器（替代原计划的 `geometry`、`layers`、`relation`）。
   - **为什么不引入 WebView**：WebView 在移动端伴学卡片内存在内存开销、手势冲突、离线 CDN 失效以及 CSS/Canvas 难以做确定性文本抽取与防泄露审查的问题，违反“方案简单”与作业防泄露红线。

2. **服务端本地毫秒级确定性 XML 校验与自动规范化（`tutor_visual.py`）**
   - 拒绝 `<!DOCTYPE`、`<!ENTITY`、`<html>`、`<body>`、注释，仅允许唯一 `<svg>` 根标签。
   - 严格标签白名单（`svg`, `defs`, `marker`, `g`, `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon`, `path`, `text`, `tspan`, `title`, `desc`, `linearGradient`, `stop`）与属性黑名单（禁止 `on*` 事件、外链 `href`/`url(http...)`、`<11px` 过小字号）。
   - 自动规范化修复：模型画带箭头的连接线 `<path>` / `<polyline>` 常漏写 `fill="none"` 导致黑色三角块，服务端确定性补齐 `fill="none"`；同时根据元素近似底边自动修正偏小的 `viewBox` 高度 `H = max(H, ceil(max_bottom + 20))` 防止底部裁切。

3. **作业题不禁用 `kind="svg"`，统一走 `describe(visual)` 防泄露闭环**
   - `extract_svg_texts` 从 SVG 语法树提取全部 `<title>`、`<desc>`、`<text>`、`<tspan>` 的可见文本，拼入 `describe(visual)`。
   - 作业受保护轮次（`answer_protected=true`）与前四种结构化图完全一致：先过确定性答案标记检查，再走并发 `visual-leak-judge` 判官与独立输出安全审核（`SafetyScreeningPort`）；判泄露、超时或异常时**只丢图、保留文字回复**。

4. **客户端 `flutter_svg` 渲染前主题色摊平（`materializeSvgTheme`）**
   - `flutter_svg` 不支持宿主的运行时动态 CSS 变量。客户端在传给 `SvgPicture.string` 前，通过 `materializeSvgTheme(svg, brightness)` 将 `var(--color-text-*)`、`var(--color-background-*)`、`var(--color-border-*)`、`context-stroke` 以及 9 色语义色板的明暗色阶替换为当前主题的十六进制颜色，保证浅色和深色模式下均有足够对比度。
