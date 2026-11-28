# 工作笔记

设计全文在 `docs/`。这里只留目标、状态、决策、注意。新决策追加到对应文件，不要新建编号笔记。进行中的验收清单放 `.agent/specs/<slug>.md`，收工后把决策并入本目录并删除 spec。

| 文件 | 何时读 |
|------|--------|
| [planning.md](planning.md) | 旧计划退场记录 |
| [companion.md](companion.md) | 对话入口、场景、消息、图片与语音 |
| [study.md](study.md) | 学习会话、到点邀请、首页任务卡 |
| [tutoring.md](tutoring.md) | 答疑、答案保护、配图、发音、离线评测 |
| [evaluation.md](evaluation.md) | 晚间客观报告、证据与记忆边界 |
| [app.md](app.md) | 登录、Ward 续期、首页、错误文案 |
| [platform.md](platform.md) | 服务端分层、Agent 配置与管理台、模型与环境 |
| [observability.md](observability.md) | Grafana、Langfuse、评测运行 |

## 产品闭环状态

事实源：[产品架构](../../docs/product/ARCHITECTURE.md)。四项目标涵盖专注、独立思考与探索、解放家长和赋能教师。Ward 可主动开启 Sprint。成人从工作台直接开始备课或批改。

| 能力 | 状态 |
|------|------|
| 身份、绑定、Ward/Guardian 首页 | Guardian 孩子首页与独立问答已交付；Ward安静首页与ASR挑战本轮实现待验收，见 [app.md](app.md) |
| 行为采集（读学 Eye） | Go网关/统一接入已实现；自动化及真实摄像头→OSS五帧短测通过，机位/长测/故障现场验收待完成。见 [网关spec](../specs/go-camera-gateway.md) |
| 主动 Sprint | 计划任务池已下线，挑战由 Study 管理；见 [planning.md](planning.md) 与进行中 spec。环境迁移核查见 [platform.md](platform.md) |
| 陪学答疑与解题凭证 | 主链路已落地。知识讲解视频未做 |
| 今日自述与晚间实况报告 | 自述已落地。证据版本化客观报告已本地实现、默认shadow，真实样本验收待完成，见进行中观察spec |
| 孩子理解 / 记忆 | 门面与边界见 [domain-memory](../../docs/technical/domain-memory.md)。自述不写入 Memory |
