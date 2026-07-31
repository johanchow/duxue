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
| 产品需求与用户手册 | [`docs/product-requirements.md`](docs/product-requirements.md) | 角色定义、摄像方案选型（A/B/C）、用户操作流程 |
| 全系统架构概览 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 四端关系、整体架构图、领域划分（限界上下文） |
| 可观测性方案 | [`docs/observability.md`](docs/observability.md) | 三端日志/链路/指标统一方案，Grafana + Loki + Tempo |

### 服务端（duxue-server）

| 文档 | 路径 | 内容摘要 |
|------|------|---------|
| 服务端架构设计 | [`duxue-server/docs/ARCHITECTURE.md`](duxue-server/docs/ARCHITECTURE.md) | 分层设计、命令与查询、AI 推理演进路线、Batch 推理与降级、数据库 ER 图、多租户隔离、数据留存 |
| VLM 分析指南 | [`duxue-server/docs/qwen3vl-student-behavior-guide.md`](duxue-server/docs/qwen3vl-student-behavior-guide.md) | Qwen3-VL 行为分析 Prompt 设计与字段定义 |

### 读学Eye（duxue-cam）

| 文档 | 路径 | 内容摘要 |
|------|------|---------|
| 技术架构设计 | [`duxue-cam/docs/ARCHITECHTURE.md`](duxue-cam/docs/ARCHITECHTURE.md) | 技术选型（CameraX/Foreground Service/Room 队列）、CaptureService 设计、绑定与抓拍上传流程、Android 14 前台服务限制 |
| CI/CD 方案 | [`duxue-cam/docs/ci_cd.md`](duxue-cam/docs/ci_cd.md) | GitHub Actions 流水线、Keystore 管理、APK 自托管分发、接入准备步骤 |

### 读学App（duxue-app）

| 文档 | 路径 | 内容摘要 |
|------|------|---------|
| 技术架构设计 | [`duxue-app/docs/ARCHITECHTURE.md`](duxue-app/docs/ARCHITECHTURE.md) | 技术选型（Riverpod/go_router/fl_chart）、模块结构、JWT 刷新设计、Riverpod Provider 示例 |
| CI/CD 方案 | [`duxue-app/docs/ci_cd.md`](duxue-app/docs/ci_cd.md) | Codemagic 双端流水线、iOS/Android 证书管理、TestFlight 与 Google Play 自动发布、接入准备步骤 |

---

## 四、核心数据流（快速理解系统）

```
摄像手机（读学Eye）
 │ 每 15 秒抓拍一张 JPEG
 ├─ 预签名 PUT ──▶ 阿里云 OSS（帧图片，不经过 API）
 └─ POST /frames ──▶ FastAPI（仅元数据）
 │
 每日 22:00：SubmitDailyBatch（当日全部帧，不做任何过滤）
 │
 百炼 Batch API（qwen3-vl-flash，单价 50%）
 │ 超 20 小时未完成 → 降级实时 API
 ▼
 structured_fields → BehaviorClassifier → FramePrediction（逐帧标签）
 │
 时序平滑 + 片段归并 → BehaviorSegment → Report
 │
Guardian（读学App）◀── GET /reports/daily ──────────────
```

> **采集是抓拍不是推流；推理是每日批量不是逐帧实时；第一期不做任何帧过滤。** 这三点是 v2.0 的核心，理解它们就能理解全系统。详见[服务端架构 §〇](duxue-server/docs/ARCHITECTURE.md)。

**AI 推理演进路线**（决定了很多设计取舍，见服务端架构 §2.5）：

```
第一期：百炼 Batch API + qwen3-vl-flash，全量帧      ← 当前
   │ 积累真实场景标注数据
第二期：用第一期数据 fine-tune 小模型（2B~7B）
   │ 黄金集上不劣于 flash
第三期：自部署 fine-tune 模型，按需启停云 GPU（非常驻）
```

这条路线解释了两个容易被质疑的决定：为什么第一期不做帧门控（跳过的帧就是缺失的训练样本，且第三期成本按 GPU 时长计而非帧数），以及为什么帧图片留存期设为 90 天而非 30 天（攒训练数据）。

---

## 五、本地开发快速启动

```bash
# 1. 启动完整后端（FastAPI + Celery worker/beat + PostgreSQL + Redis）
cd duxue-server
docker compose up -d

# 2. 启动 Cam App（Android Studio 真机调试）
# 将 API 地址改为本机 IP：http://192.168.x.x:8000
# 本地开发可把 OSS 换成 MinIO，预签名 URL 接口保持兼容

# 3. 启动 Guardian App（Flutter）
cd duxue-app
flutter run -t lib/main_mock.dart   # Mock 模式，不依赖后端
# 或
flutter run                          # 连接本地 Docker 后端
```

---

## 六、尚未建设的内容

| 内容 | 说明 |
|------|------|
| `duxue-admin/` | Admin Web 运营后台，技术方案待定。产品文档中方案 B/C 依赖它，故这两个摄像方案当前标注为"暂未开放" |
| 推送通道 | 设备掉线通知与报告就绪通知都需要推送。iOS 走 APNs，国内 Android 需接厂商通道或极光/个推。尚未排期，但直接影响留存 |
| 移动端测试文档 | Cam App 和 Guardian App 的测试方案待补充到各自 docs/ |
| 部署运维文档 | 生产环境 Docker Compose / K8s 部署方案待补充到 duxue-server/docs/ |
| Badcase 反馈入口 | App 时间轴上的"这段标错了"按钮及配套标注池，设计见服务端架构 §9.3。它同时是第二期 fine-tune 训练数据的主要来源，尚未实现 |
| 分类层配置重写 | `classifier/categories.yaml` 中依赖"目光"的参考短句需按新机位（不拍正脸）重写，**必须在标注开始前完成** |
| 自部署推理（第二/三期） | fine-tune 模型 + 按需启停 GPU 实例。前置依赖是第一期积累的标注数据，因此第一期必须全量保留帧图片 |
