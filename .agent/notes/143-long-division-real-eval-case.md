# 真实除法竖式结果纳入离线评测

将线程 `5fcce68a` 最新成功轮（trace `ed927a30e8119ae58ac99ca1e8f8ddae`）收录为 `visual/long_division_regression.jsonl` 中的单步 `proposed` 用例。历史窗口取自本机审计日志的可见文字；上下文中的开放题状态是重放摘要，待人工核对。

自动断言覆盖 `hint_like`、最终展示 `visual.svg`、正文不以 `\enclose{longdiv}` / TeX array 冒充图，以及图中不出现先前错误的 `)` 和提前填出的商 `5`。SVG 的「厂」字几何目前不在确定性 grader 的能力范围内，仍需人工看图；因此不将此条标为 `confirmed`。
