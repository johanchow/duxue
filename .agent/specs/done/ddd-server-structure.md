---
slug: ddd-server-structure
created: 2026-09-13T15:52:58Z
status: done
---

# 服务端 DDD 目录重构

## 做什么 / 为什么
将 `duxue-server` 从当前扁平的 `app/*.py` 和单一 `app/main.py` 路由入口，迁移为
根目录 `app/` 源码布局下的 Interface/API、Application、Bounded Context Domain、Infrastructure、
Worker 与 Bootstrap 分层；保持对外 HTTP/SSE/WebSocket、数据库 Schema、Celery task 名称和
业务行为兼容。这里的“整个项目”指前文讨论的 **duxue-server**；Flutter 与 Android 端不采用
Python `app/` 布局，本次不移动它们。

## 验收标准
- [x] 服务端源码唯一位于 `duxue-server/app/`，运行、Docker Compose、Alembic、测试均可从该源码根加载 `app` 包；旧扁平模块与顶层 `infrastructure/` 不再保留生产源码。
- [x] API 层由 `api/v1/` 与 `api/router.py` 统一装配，保持所有现有 URL、方法、状态码、SSE/WebSocket 行为和认证语义不变。
- [x] Application 层位于顶层 `application/`：按 Command/Query/Workflow 组织，用 `process_managers/` 放置跨 Context 编排（含 Companion Coordinator）。
- [x] 八个已定义 Bounded Context 均拥有独立 `contexts/<context>/domain/` 命名空间；跨 Context 协作仍经 application port、受权 query 或 Outbox/版本化事件进行。
- [x] SQLAlchemy、存储、AI、认证、可观测性、消息与 Celery adapter 已归入 `infrastructure/`；Worker 入口位于 `workers/`，task 名称不变。
- [x] 迁移未改变已有 Alembic revision、数据库表名、环境变量、Docker service 名称和 `duxue.*` Celery task name；README 与技术设计已同步目录结构。
- [x] 现有服务端 pytest 全绿，新增架构契约测试覆盖源码根、API router 装配与 Process Manager 位置。

## 实现计划（Gate 1：填完等人确认，不许自转）

### 目标目录

```text
duxue-server/
├── app/
│   ├── bootstrap/                 # settings、FastAPI factory、DI 装配
│   ├── api/                       # Interface：v1 routers、deps、DTO、error mapping
│   ├── application/               # Commands、Queries、Process Managers、Ports
│   │   ├── commands/<context>/
│   │   ├── queries/<context>/
│   │   ├── process_managers/
│   │   └── ports/
│   ├── contexts/
│   │   ├── identity/domain/
│   │   ├── device_ingestion/domain/
│   │   ├── planning/domain/
│   │   ├── study/domain/
│   │   ├── behavior_analysis/domain/
│   │   ├── evaluation/domain/
│   │   ├── memory/domain/
│   │   └── companion/domain/
│   ├── infrastructure/            # persistence、messaging、ai、storage、security、observability
│   └── workers/                   # Celery task entrypoints
├── migrations/
└── tests/
```

### 迁移策略与影响文件

1. 建立 `app` 包与启动装配；更新 `Dockerfile`、Compose、`run.py`、Alembic、README，使生产和开发均从 `app` 导入。先添加迁移前后的启动/导入契约测试。
2. 将 `main.py` 拆成 `bootstrap/app.py` 与 `api/v1/` 的身份、Ward、设备、计划、学习、复盘、伴学、分析和管理路由。每个 router 只保留 HTTP 边界转换；现存 handler 的业务实现先原样搬入 Application command/query，确保 API 无 ORM 模型导入。
3. 提取顶层 `application/commands`、`queries`、`process_managers` 与 `ports`。原 `ai_runtime/companion_coordinator.py` 迁入 `application/process_managers/companion_coordinator.py`；Planning/Tutoring/Reflection workflow 归入对应 Application 工作流，不作为 Domain Aggregate。
4. 按 DDD Overview 的八个 Context 迁移纯领域规则、Aggregate/值对象、Repository Port、领域事件；先保持 SQLAlchemy 映射与已有物理 Schema 完全兼容。禁止 Domain 依赖 FastAPI、Celery、SQLAlchemy 或模型 SDK。
5. 将 `database.py`、`models.py` 及各 adapter 拆入 `infrastructure/persistence/<context>/`，把 AI、OSS、JWT、ASR、Outbox、遥测拆到相应基础设施子目录；保留临时的内部 facade/import re-export 仅在迁移期间使用，最终移除。
6. 迁移 Celery 与定时任务至 `workers/` 和 `infrastructure/messaging/`：task 名称、队列行为不变，task 函数只调用 Application 层。
7. 更新所有测试 import 与 mock patch 目标；补架构测试、运行格式化/静态检查/完整 pytest；检查 diff。更新 `design-server.md` 的目录图和 `.agent/notes/` 决策记录。

### 明确不做

- 不修改 Flutter (`duxue-app`) 或 Android (`duxue-cam`) 的业务、目录和 API 调用。
- 不重写业务规则、不改 API contract、不引入微服务、不变更数据库 Schema 或历史 Alembic revision。
- 不以“目录移动”为名让 Domain 直接使用 ORM；若现有代码尚未可完全剥离，将显式建立 Port/Adapter，而不是伪装分层。

### 测试计划

- 先运行当前 `pytest tests -q` 记录基线；每一阶段执行受影响的 unit/application/contract tests。
- 新增 `tests/architecture/`：验证 `app` 是唯一生产包、API router 装配的路径集合等价、Process Manager 位于 Application。
- 最终执行完整 pytest、导入与 Docker/Alembic 入口 smoke check、`git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 记录基线并建立 `app` 启动与测试路径
- [x] 拆分 API router 与 Bootstrap，保持 HTTP contract
- [x] 建立顶层 Application commands / queries / process managers / ports
- [x] 按八个 Context 落位 Domain 模块与依赖边界
- [x] 迁移 Persistence、AI、Storage、Security、Messaging、Observability infrastructure
- [x] 迁移 Worker/Celery 入口并保持任务契约
- [x] 更新测试、补架构契约测试并全量验证
- [x] 同步技术设计与决策笔记，完成 diff review

## 备注

- 目录边界以 `docs/technical/ddd-overview.md` §2、§5 的 Context Map 与 Layered Architecture Map 为准；物理表与迁移以 `docs/technical/design-server.md` 为准。
- 根目录 `app/` 保留当前包名，避免不必要的包名、容器入口与测试生态破坏。
