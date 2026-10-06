# 计划整理去掉 items，模型追问直接展示

模型输出不再接受 `items`。要写入任务，必须给 `operations`。缺标题或预计时长时，仍由服务端按操作补槽。

没有操作、但 `clarification_required=true` 时，把 `assistant_text`（以及其中没写过的 `questions`）原样交给学生。下一次回答仍是普通规划回合，由模型决定是否输出 `operations`。图片读不清且模型没有提出问题，才使用「没有识别出新任务」。
