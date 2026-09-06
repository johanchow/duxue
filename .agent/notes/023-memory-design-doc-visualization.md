# 记忆设计文档可视化

- `docs/technical/design-memory.md` 的总体架构不再维护与正文重复的 ASCII 图；交互式数据流图是该章节的视觉入口，正文仍是语义与契约的唯一事实源。
- 图源 `docs/technical/diagrams/design-memory-dataflow.json` 固化“领域服务同事务写状态、事实与 Outbox；Worker 派生记忆；MemoryFacade 最小化召回”的数据边界。
- Working Memory 保持为运行时会话状态，因其与异步派生链路并行，图中以结论卡说明而不伪装为从事件账本直接生成的长期存储。
- 图的浏览器自动证据依赖 Chrome DevTools；本次本机 Chrome 以 `SIGABRT` 退出，交付的静态 9 项校验通过，但浏览器证据需在可用 Chrome 环境重新采集。
