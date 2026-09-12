# Domain 技术设计文档所有权

- `domain-companion.md` 只拥有入口 Thread/Run、Coordinator、Handoff、通用 Outcome/SSE 和跨 Context 调用协议；不再承载 Planning、Study、Evaluation 的业务模型或具体 Workflow。
- `domain-planning.md`、`domain-study.md`、`domain-evaluation.md` 分别拥有本 Context 的 Aggregate、不变量、Use Case、Workflow Definition、Working State、实际工具/模型候选边界、Fact/Outbox 与目标 UI 契约。
- `domain-memory.md` 继续唯一拥有事实账本、情境记忆、Signal/Profile 和删除/衰减语义；`design-server.md` 只拥有表、索引、运行时、API/Worker/部署等物理映射，并以 Context 索引链接各 Domain 文档。
- `ddd-overview.md` 继续唯一拥有系统级 Context Map、跨 Context 所有权和稳定 Integration Event；其他文档只链接，不复制其细节。
