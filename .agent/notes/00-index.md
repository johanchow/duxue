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
| [platform.md](platform.md) | 服务端分层、Agent 配置与管理台、模型与环境 |
| [observability.md](observability.md) | Grafana、Langfuse、评测运行 |

## 产品闭环状态

事实源：[产品架构](../../docs/product/ARCHITECTURE.md)。三大核心目标：提升专注效率、引导独立思考、解放家长陪读时间。线上建 Plan 与手动标记完成均为弱约束可选增强，不阻塞核心伴学与报告交付。

| 能力 | 状态 |
|------|------|
| 身份、绑定、Ward/Guardian 首页 | Guardian 报告首页已交付；Ward安静首页与ASR挑战本轮实现待验收，见 [app.md](app.md) |
| 行为采集（读学 Eye） | Go网关/统一接入已实现；自动化及真实摄像头→OSS五帧短测通过，机位/长测/故障现场验收待完成。见 [网关spec](../specs/go-camera-gateway.md) |
| 轻量计划与主动 Sprint | 本轮已改造实现，待 Gate 2；见 [planning.md](planning.md) 与进行中 spec。测试库已升级至34，生产未迁移 |
| 陪学答疑与解题凭证 | 主链路已落地。知识讲解视频未做 |
| 今日自述与晚间实况报告 | 自述已落地。证据版本化的客观报告未做 |
| 孩子理解 / 记忆 | 门面与边界见 [domain-memory](../../docs/technical/domain-memory.md)。自述不写入 Memory |
