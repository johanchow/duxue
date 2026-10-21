# 除法竖式被写进文字而未返回配图

2026-10-21 09:18（北京时间）trace `4c458203d4522f5b0a57d697b3c2c45e`：用户说「重新画一下图」，模型返回 `content` 中的 `\enclose{longdiv}{660}`，但没有 `visual`。服务端 `tutor.turn.result` 为 `shown`，没有 `tutor.visual.kind`；App 收到的是纯文字交互，因此无图可渲染。

根因是主提示词虽要求二维竖式走 `visual.svg`，模型仍把 TeX 排版误当作可显示的图。修复后，明确禁止用 TeX array / `\enclose{longdiv}` 代替配图；当这类输出缺少 `visual` 时，携带 `widget_guidelines` 和失败草稿重画一次，必要时再用备用模型重试。只有 `svg` 通过完整出口检查且正文不再含该 TeX 命令时才采用。

服务端全量测试 580 项通过；改动文件 Ruff 和 `git diff --check` 通过。
