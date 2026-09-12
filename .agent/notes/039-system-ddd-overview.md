# 系统级 DDD Overview

- `docs/technical/ddd-overview.md` 是全系统 Domain Inventory、DDD Context Map、跨 Context
  所有权和稳定 Integration Event 契约的唯一来源；它不承载表、ORM、队列、Controller 或
  Aggregate 内部细节。
- `design-server.md` 保留系统分层、物理 Schema、运行时与运维；各 Context 详情页保留
  聚合、用例、不变量、CQRS 与局部事件流。共享 PostgreSQL 不表示可跨 Context 直接写入。
- Context Map 与 Layered Architecture Map 需分开：前者表达业务所有权与集成契约，后者
  表达 Interface → Application → Domain Context → Infrastructure 的依赖方向。
- `Memory & Understanding Context` 的 Working Memory 不属于其写 Aggregate，而属于
  `Companion Orchestration` Runtime；其详细边界以 `design-memory.md` 为准。
