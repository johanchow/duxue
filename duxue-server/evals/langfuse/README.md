# Langfuse 资源索引与只读定义快照

`resources.json` 记录项目、Dataset、Evaluator、Score Config 和共用复核队列的稳定 ID，供 runner 定位资源。

`deterministic.py`、`judges.json` 是初始化/审计快照，**不是另一套运行时 grader**。评分逻辑在 Langfuse 编辑并形成版本；runner 启动时下载当前定义用于审计，全部评分由云端执行。本地 Code 快照测试通过不代表当前远端版本已通过人工校准。

`deterministic.py` 的 `Score` / `EvaluationResult` 由 Langfuse 沙箱注入，无本地运行入口。未来修改云端定义后，可显式导出更新快照，不能只改本地文件并认为远端已变更。

协议与命令唯一归属：[离线评测设计](../../../docs/technical/eval-offline.md)。
