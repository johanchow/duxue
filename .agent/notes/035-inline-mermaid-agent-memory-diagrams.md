# Agent 与 Memory 文内 Mermaid 图

- `design-agent.md` 与 `design-memory.md` 不再依赖外部 HTML 图作为设计正文；Context Map、Aggregate/Internal Model、状态机与 Command–Event–Projection 数据流均改为文内 Mermaid，便于在 GitHub、飞书 Markdown 等渲染器中就地阅读和评审。
- 关系图优先表达所有权和一致性边界：实线用于命令/稳定事实，虚线用于受权只读或运行时候选；跨 Context 不共享 Aggregate。
- 原有 `docs/technical/diagrams/*.html` 和 JSON 图源暂不删除。它们已不被两份设计文档引用，保留是为了避免未经确认地移除历史资产；若确认不再需要，可在独立清理变更中一并删除。
