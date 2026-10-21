# 138 — `visual_invalid` 重试带回草稿 + SVG 确定性清洗

## 现象

Thread `5fcce68a-2996-4ae9-bb6c-c9968230d956`（`trace_id` `eb2c5076ecb26cfb21cf382645fc72db`）：孩子纠正“是说六百六十除一百五十。的除法竖式。怎么写？”。模型第一次已经写出 `660 ÷ 150` 并附了 `kind="svg"`，但：

1. 未调 `widget_guidelines`，`viewBox="0 0 300 200"` 且只有 `<text>`，校验失败；
2. `visual_invalid` 重试只告诉模型“保持 act/content/turn 不变”，**没附上一版草稿**，也**没注入 SVG 规范**；
3. 重试时模型只看见上一轮自己写的 `$660 \div 15$`，正文退回错误数字；第二次 SVG 虽已是 `0 0 680`，却带了 `<style>`，再次被丢。

孩子最终只看到 `$66 \div 15$` 的纯文字。

## 根因

- `call_tutor_model` 的 visual 重试只写错误类别，不回传被拒的 `act/content/turn/visual`。
- 模型强制“先调 `widget_guidelines` 再写 svg”，但代码在未调工具就写坏图时不会代为注入规范。
- `_validate_and_normalize_svg` 把无害包装（`<style>`、非 680 宽 `viewBox`）当成整张图非法。高度与注释早已做确定性清洗，宽度和 `<style>` 没有。

## 修复

1. `tutor_loop._visual_repair`：重试 `repair_error` 附带有界的上一版 `act/content/turn/visual`。`kind=svg` 且 observations 里还没有 `widget_guidelines` 时，注入 `SVG_WIDGET_GUIDELINES`（不占工具预算）。
2. `tutor_visual.py` / App `SvgData.tryParse`：剥离 `<style>` 块（与 XML 注释同类），`viewBox` 原点为 `0 0` 且高度合法时把宽度改写为 680。`<script>`、外链、无图形等仍整张丢弃。

未做：不往提示词或 `SVG_WIDGET_GUIDELINES` 加竖式模板、口语数字或“除/除以”特例。
