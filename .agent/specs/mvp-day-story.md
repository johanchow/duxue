---
slug: mvp-day-story
created: 2026-08-22T02:34:40Z
status: draft
---

# mvp-day-story spec

## 做什么 / 为什么
在一个自用家庭中跑通「家长提交作业与绑定闲置机 → Ward 确认当天计划 → 伴学执行与持续抓拍 → 当晚盲评、双轨复盘与一条行动锦囊 → Guardian 事实报告和沟通建议」的可验收闭环。复用既有设备直传、行为分析和日报能力，以同一份会话事实分别服务 Ward 与 Guardian。

## 验收标准
- [ ] Guardian 可创建 Ward、提交文字作业、生成设备邀请码；Cam 端用邀请码绑定后保持心跳，并按既有 15 秒节奏抓拍、直传 OSS、上报帧元数据。
- [ ] Ward 能通过受限身份进入自己的空间，看到待办作业，创建并确认只属于自己的当天计划；Guardian 只能提交作业、查看计划，不能创建、修改或确认计划。
- [ ] Ward 能开始计划任务、暂停/恢复/完成并获得累计用时；能够发送文字问题并获得启发式、分步骤的答疑，问答与卡点事实写入会话。
- [ ] Ward 完成当天计划后，先在不暴露客观行为数据的情况下提交自评；提交后立刻看到主观自评与 AI 行为记录的双轨时间轴、基于事实的归因和一条可保存的行动锦囊。
- [ ] Guardian 在 Ward 提交自评后能看到同一晚的事实报告（计划完成、用时、行为节奏、答疑卡点）及 1–2 条基于事实的正向沟通建议；自评前报告不得泄露客观分析细节。
- [ ] 所有新增数据均由 Alembic 管理；角色、家庭和 Ward 归属在服务端强制鉴权，跨家庭或 Guardian 越权修改 Ward 计划均被拒绝。
- [ ] 新增后端单元/API 集成测试及 Flutter model/widget 测试通过；现有 Server、Flutter 和 Cam 测试不回归。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/{models,schemas,dependencies,services,ai,main}.py`：新增 Ward 登录与绑定、作业/计划/学习会话/问答/自评/锦囊/双视角报告领域模型、鉴权与 API；将日行为分析关联到当日学习会话。
  - `duxue-server/migrations/versions/`：新增可升级、可回滚的 Alembic 表结构迁移；同步数据清理链路。
  - `duxue-server/tests/`：为角色边界、全链路状态流转、报告锁定与迁移关键约束补足测试。
  - `duxue-app/lib/`：由当前 Guardian-only 路由升级为角色选择、Guardian 作业/设备/报告页和 Ward 计划、伴学、自评/双轨页；扩展 API client、模型和 Riverpod 状态。
  - `duxue-app/test/`：覆盖新增 API JSON 模型、锁定报告解析与核心状态/组件。
  - `duxue-cam/`：只在服务端契约不兼容时作最小改动；当前绑定/上传/心跳端点可直接复用。
  - `.agent/notes/`：记录身份与会话聚合等决定、环境坑和验收结果。
- 实施顺序：先确定 Ward 身份与 AI 服务策略；再完成服务端迁移、领域与 API 并以 API 测试锁住角色边界；随后完成 Flutter 双角色闭环；最后以本地/已配置环境运行迁移、全量测试和端到端验收。
- 测试计划：FastAPI `TestClient` 覆盖 Guardian→Ward→Device→Session→Self-review→两类报告全链；测试 Guardian 无法写/确认计划和 Ward 自评前无法读取客观报告；执行 Alembic upgrade 验证；`pytest`、`flutter test`、Cam Gradle 测试均全绿。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 确认 Ward 身份、AI 供应商策略与验收环境
- [x] 建立迁移及服务端领域/API/鉴权测试
- [x] 完成 Guardian 作业、设备与报告入口
- [x] 完成 Ward 绑定、计划确认、伴学问答与自评双轨
- [ ] 接入真实设备上传、行为分析与报告聚合
- [ ] 全量测试、人工走通一日故事并记录决策

## 备注
- 当前已知不确定项：Ward 的登录/绑定方式、伴学/报告是否必须调用已配置通义模型而非确定性 MVP 降级、以及本次是否授权连接配置中的实际 PostgreSQL/OSS 做验收。未确认前不实施这些会影响账号安全、成本或外部数据的部分。
- 决策（2026-08-22）：Ward 使用 Guardian 签发的一次性绑定码设置本机 PIN；答疑、归因、Guardian 沟通建议按用途分别配置模型名称，默认回退到既有 VLM 模型。当前服务端答疑提供安全的苏格拉底式降级文案，模型适配器尚待接入。
