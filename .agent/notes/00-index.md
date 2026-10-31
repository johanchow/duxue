# 工作笔记

设计全文在 `docs/`。这里只留目标、状态、决策、注意。新决策追加到对应文件，不要新建编号笔记。进行中的验收清单放 `.agent/specs/<slug>.md`，收工后把决策并入本目录并删除 spec。

| 文件 | 何时读 |
|------|--------|
| [planning.md](planning.md) | 任务池、排期、确认、删除 |
| [companion.md](companion.md) | 对话入口、场景、消息、图片与语音 |
| [study.md](study.md) | 学习会话、到点邀请、首页任务卡 |
| [tutoring.md](tutoring.md) | 答疑、答案保护、配图、发音、离线评测 |
| [evaluation.md](evaluation.md) | 今日总结、复盘意图、记忆边界 |
| [app.md](app.md) | 登录、Ward 续期、首页、错误文案 |
| [platform.md](platform.md) | 服务端分层、Agent 配置、模型与环境 |
| [observability.md](observability.md) | Grafana、Langfuse、评测运行 |

## 产品闭环状态

事实源：[产品架构](../../docs/product/ARCHITECTURE.md)。当前是自用验证期。G3（家庭关系）尚未验证，不要据此开工。

| 能力 | 状态 |
|------|------|
| 身份、绑定、Ward 首页 | 已落地。见 [app.md](app.md) |
| 行为采集（读学 Eye） | 按 [design-cam](../../docs/technical/design-cam.md)。到点邀请尚未使用现场画面 |
| 协商计划 | 已落地。执行中改计划、一任务多段时间未做 |
| 陪学答疑 | 主链路已落地。知识讲解视频未做。兴趣探索未做 |
| 今日自述与复盘对话 | 自述已落地。证据版本化的客观报告未做 |
| 家庭关系深度引导、产物归档分享 | 未做 |
| 孩子理解 / 记忆 | 门面与边界见 [domain-memory](../../docs/technical/domain-memory.md)。自述不写入 Memory |
