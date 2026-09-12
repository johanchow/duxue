# Server Memory 专属映射移除

- `domain-memory.md` 是 Memory Context 的 Infrastructure Mapping 唯一来源：它定义 Repository/Consumer/Projection/Outbox/Worker 的 Context 责任，并链接 `design-server.md` 的物理表、索引、队列和运维细节。
- `design-server.md` 保留全服务器的物理 Schema、索引、队列、留存和部署，不再按单个 Domain 重复“领域概念 → 物理实现”映射表；否则该表会成为第三处可漂移的事实源。
