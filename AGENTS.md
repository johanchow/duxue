# 读学系统 — 项目导航（AGENTS.md）

> AI 阅读本文档可快速定位各端架构、技术决策和关键文档，无需遍历全仓库。

---

## 一、项目目标与设计原则

读学系统是一款基于 AI 视觉分析的行为观察平台。产品和技术方案始终围绕以下三个原则：

### 用户简单

- **guardian（监护人）** 无需任何技术背景，只需扫码绑定摄像设备，报告自动生成
- **摄像设备** 使用家里闲置的 Android 手机即可，零额外硬件成本
- 所有分析配置有合理默认值，不配置也能正常工作

### 方案简单

- 每一层只做一件事：摄像端只抓拍上传、服务端只分析、App 只展示
- 不引入过度设计：无微服务拆分、无复杂消息总线、无第三方 Auth 服务
- 技术选型优先选生态成熟、文档完整的主流方案，降低维护成本

### 智能自动化

- guardian 设置好摄像设备后，帧采集 → AI 分析 → 报告生成 全程自动，无需人工干预
- CI/CD 全自动构建、测试、发布，代码合并后自动推测试版
- 可观测性完整覆盖三端，问题定位不依赖人工排查

---

## 二、四端组成与目录结构

```
duxue/                          # 项目根目录
├── docs/                       # 全系统级文档
├── duxue-cam/                  # 读学Eye：Android 摄像端
│   └── docs/
├── duxue-app/                  # 读学App：Guardian 端（Flutter）
│   └── docs/
├── duxue-admin/                # Admin Web：运营后台（待建设）
└── duxue-server/               # 服务端：FastAPI + Celery + OSS
    └── docs/
```

| 端 | 目录 | 角色 | 技术栈 |
|----|------|------|--------|
| 读学Eye | `duxue-cam/` | Android 采集端，定时抓拍上传 | Kotlin · CameraX · Foreground Service · Room |
| 读学App | `duxue-app/` | Guardian 端，查看报告 | Flutter · Riverpod · fl_chart |
| Admin Web | `duxue-admin/` | 运营后台，机构管理 | 待定 |
| Server | `duxue-server/` | REST API · AI 推理编排 · 数据存储 | FastAPI · PostgreSQL · Celery · OSS |

---

## 三、关键文档索引

### 产品与系统全局

| 文档 | 路径 | 内容摘要 |
|------|------|---------|
| 产品架构（模块地图 + OpenSpec 规格） | [`docs/product/ARCHITECTURE.md`](docs/product/ARCHITECTURE.md) | 产品愿景与三大目标、ward/guardian 角色、五场景闭环、按角色划分的模块地图（§四）、各能力的 Requirement/Scenario 规格（§五） |
| 用户与首页导航 PRD | [`docs/product/prd-user.md`](docs/product/prd-user.md) | 用户角色选择、登录、家庭绑定、Ward/Guardian 首页与各 Tab 导航设计 |
| 协商式计划 PRD | [`docs/product/prd-schedule.md`](docs/product/prd-schedule.md) | Ward 任务池汇总、多模态意图表达、AI 计划草稿生成、可视化审阅确认与权限边界 |
| 陪伴执行与 AI 陪学问答 PRD | [`docs/product/prd-companion.md`](docs/product/prd-companion.md) | 沉浸伴学工作台、启发式分步答疑、好奇心/兴趣信号捕获、轻量成就收尾与安全护栏 |
| 结果评估与复盘引导 PRD | [`docs/product/prd-evaluate.md`](docs/product/prd-evaluate.md) | 今日即时自评先行、AI 客观行为双轨对比、专注归因与行动锦囊、家长正面沟通建议 |
| 学习观察与行为采集 PRD | [`docs/product/prd-supervise.md`](docs/product/prd-supervise.md) | 读学Eye Android 闲置机接入、稀疏定时抓拍（15s/帧）直传 OSS、Room 断网补传、健康心跳与 45° 机位隐私防护 |
| 孩子理解引擎与记忆系统 PRD | [`docs/product/prd-memory.md`](docs/product/prd-memory.md) | 纯系统智能底座、三层记忆架构（短期工作/近5天事件/长期画像）、抽取与衰减管道、跨模块上下文注入 |
| 用户核心价值与故事 | [`docs/product/user-story.md`](docs/product/user-story.md) | Jobs-to-be-Done 框架、小宇与林女士的用户旅程故事 |
| 摄像设备接入与操作手册 | [`docs/camera-setup-guide.md`](docs/camera-setup-guide.md) | 摄像方案选型（A/B/C）、机位指引、设备绑定操作步骤、设备类 FAQ |
| 全系统技术架构概览 | [`docs/technical/ARCHITECTURE.md`](docs/technical/ARCHITECTURE.md) | 四端分工、领域模型（限界上下文）、会话即时分析管线、Guardian-Ward 绑定与权限模型 |
| 可观测性方案 | [`docs/observability.md`](docs/observability.md) | 三端日志/链路/指标统一方案，Grafana + Loki + Tempo |

### 服务端（duxue-server）

| 文档 | 路径 | 内容摘要 |
|------|------|---------|
| 服务端详细设计 (No-Tenant) | [`docs/technical/design-server.md`](docs/technical/design-server.md) | 分层实现、无租户模型与直连绑定、数据库 ER 图、会话即时分析与伴学记忆引擎 |
| 孩子理解与记忆技术设计 | [`docs/technical/design-memory.md`](docs/technical/design-memory.md) | 事实事件账本、Signal/Claim、三层记忆与表映射、更新/衰减、答疑情境记忆与数据删除边界 |
| 陪伴 Agent 技术设计 | [`docs/technical/design-agent.md`](docs/technical/design-agent.md) | 统一入口路由、计划协商 Graph、启发式答疑 ReAct、今日复盘、AI Runtime 与受控写回 |
| VLM 分析指南 | [`duxue-server/docs/qwen3vl-student-behavior-guide.md`](duxue-server/docs/qwen3vl-student-behavior-guide.md) | Qwen3-VL 行为分析 Prompt 设计与字段定义 |

### 读学Eye（duxue-cam）

| 文档 | 路径 | 内容摘要 |
|------|------|---------|
| Cam 端详细技术设计 (v3.0) | [`docs/technical/design-cam.md`](docs/technical/design-cam.md) | 稀疏抓拍与预签名直传、零端侧推理、Room 离线容灾队列、Android 14+ 前台服务保活与 60s 单调时钟心跳 |
| CI/CD 方案 | [`duxue-cam/docs/ci_cd.md`](duxue-cam/docs/ci_cd.md) | GitHub Actions 流水线、Keystore 管理、APK 自托管分发、接入准备步骤 |

### 读学App（duxue-app）

| 文档 | 路径 | 内容摘要 |
|------|------|---------|
| App 端详细技术设计 (v3.0) | [`docs/technical/design-app.md`](docs/technical/design-app.md) | 双角色路由与隔离、Riverpod 2.x 响应式状态机、SSE 流式与 LaTeX 混排、双轨对比 CustomPainter、多 Ward 切换与共管 |
| CI/CD 方案 | [`duxue-app/docs/ci_cd.md`](duxue-app/docs/ci_cd.md) | Codemagic 双端流水线、iOS/Android 证书管理、TestFlight 与 Google Play 自动发布、接入准备步骤 |

---

## 四、开发规范
> 每个 AI 会话开工前必读的最高约定。本文只放**铁律**与**导航**。

## 铁律（不可违反）

1. **先读后写**：动手前必读相关 spec（`.agent/specs/`）+ 相关笔记（`.agent/notes/`）。
2. **测试是退出条件**：改行为必带测试；测试全绿才算完，不许自评「我觉得做完了」。
3. **单一事实源**：一类知识只在唯一归属处写一份，别处只**链接**、不 copy。
4. **收工必沉淀**：loop 结束前把决策 / 坑记进 `.agent/notes/`，否则不算收工。
5. **commit 前必 review**：`git diff` 确认设计合理、无调试残留、无遗漏文件；文档与代码同一 commit，**不许 commit 后补文档**。
6. **代码不出本地**：调用本机 CLI Agent，不外传代码。
7. **环境不绕过**：版本 / 包管理器以本仓库约定为准（如 `.nvmrc` / `pnpm` / `npm`），严禁绕过引擎严格模式的直调。

## 导航（去哪读 / 去哪写）

| 我想… | 看 / 写这里 |
|-------|------------|
| 开新 feature | `/feature-spec` skill（或读 `.agent/loops/feature.md`） |
| 修 bug | `.agent/loops/bugfix.md` |
| 记决策 / 踩坑 | `.agent/notes/`（新建 `NNN-<topic>.md`） |

## 干活的标准流程

- **新 feature（单文件 + 2 卡点）→ `/feature-spec`**：验收标准 + 实现计划 + 完成度清单，计划确认、验收两次人工卡点。详见 `.agent/loops/feature.md`。
- **修 bug → `.agent/loops/bugfix.md`**：先写复现测试（红）→ 最小修复（绿），记坑。

## 多 spec 管理

- spec 文件：`.agent/specs/<slug>.md`（单文件，含验收 + 计划 + 清单）。
- 完成归档：`.agent/specs/done/<slug>.md`（跑 `archive-spec.sh`）。
- 新建：`bash .agent/scripts/new-spec.sh <slug>`；归档：`bash .agent/scripts/archive-spec.sh <slug>`。
