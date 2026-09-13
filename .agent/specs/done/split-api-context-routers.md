---
slug: split-api-context-routers
created: 2026-09-13T23:38:03Z
status: done
---

# 按 Context 拆分 API Router

## 做什么 / 为什么
将 `duxue-server/app/api/v1/routes.py` 的 60 余条路由按 DDD Context 拆为独立的
FastAPI `APIRouter` 模块。`api/router.py` 只负责统一注册；路径、HTTP 方法、响应、鉴权和
OpenAPI 行为保持不变。本次只整理 Interface 层，不趁机改变领域或 Application 用例。

## 验收标准
- [x] 不再存在包含业务路由的 `api/v1/routes.py` 单体文件；每个 API endpoint 只由一个 Context router 注册。
- [x] 新建并注册 `system`、`identity`、`device_ingestion`、`planning`、`study`、`evaluation`、`memory`、`companion`、`behavior` routers；每个 router 的职责和 Context Map 一致。
- [x] 所有现有 URL、方法、状态码、响应模型、SSE/WebSocket、认证依赖与 Celery/数据库业务效果保持兼容。
- [x] API 汇总器不包含 endpoint 函数；Bootstrap 仍只创建 FastAPI 并 include 顶层 API router。
- [x] 更新 mock patch 目标、补 API 路由结构与 OpenAPI path 集合的契约测试；服务端 pytest 全绿。

## 实现计划（Gate 1：填完等人确认，不许自转）

### 目标布局

```text
app/api/
├── deps.py
├── schemas.py
├── router.py                    # 仅 include v1 routers
└── v1/
    ├── common.py                # 小型、无 endpoint 的 HTTP 辅助函数
    ├── system.py                # health、telemetry、ASR websocket
    ├── identity.py              # auth、Ward 身份、Guardian-Ward 关系
    ├── device_ingestion.py      # device、upload、frame
    ├── planning.py              # task intake、计划、assignment
    ├── study.py                 # study session、tutoring message
    ├── evaluation.py            # self review、report、guardian story
    ├── memory.py                # signal challenge
    ├── companion.py             # turn、run cancel、SSE replay
    └── behavior.py               # profile、label、analysis、frame query
```

### 实现计划（Gate 1：填完等人确认，不许自转）

1. 在迁移前记录现有 OpenAPI 的 `(path, method)` 集合并运行当前完整 pytest 基线。
2. 提取仅供 Interface 层使用的 token 签发、报告序列化、Ward ownership 等无路由辅助函数至 `v1/common.py`；不让 helper 反向导入 router。
3. 逐个把 endpoint 与其最小 import 集合迁入上述 Context router；每个模块拥有自己的 `APIRouter(tags=[...])`。路由 decorator、函数体和 DI 声明不改变。
4. 将 `api/router.py` 改为唯一汇总器；删除旧 `v1/routes.py`，保留 Bootstrap → API router 的单向装配。
5. 更新测试中对 endpoint module 的 import/mock patch，新增 OpenAPI path 集合等价、router 不重叠、汇总器无 endpoint decorator 的架构契约测试。
6. 更新技术设计和决策笔记，运行完整 pytest、格式与 diff 检查。

### 测试计划

- 运行迁移前后 `app.openapi()`，比较路径和每条 path 的 HTTP method 集合。
- 运行既有 unit/application/integration/contract/e2e 测试；WebSocket 与 endpoint mock patch 回归。
- 静态检查：`api/router.py` 仅导入/注册 router，`v1/*.py` 恰有一个 `APIRouter`，不存在 `v1/routes.py`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 记录 OpenAPI 与 pytest 基线
- [x] 建立 API common helper 和 Context router 模块
- [x] 迁移 system、identity、companion、memory endpoints
- [x] 迁移 planning、study、evaluation endpoints
- [x] 迁移 device ingestion、behavior endpoints
- [x] 汇总 router、删除单体 routes 并更新 mock patch
- [x] 补 router/OpenAPI 架构契约并全量验证
- [x] 同步技术设计与决策笔记，完成 diff review

## 备注
