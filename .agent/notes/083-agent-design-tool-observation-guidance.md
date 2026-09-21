# Agent Design Tool Observation Guidance

日期：2026-09-21

- 背景：Planning 调试暴露出“伪 Agent Loop”风险：模型看似在 loop 中处理澄清，实际边界规则散落在 adapter 和大函数里，空候选 `target_task_ids` 被错误包装成可回答问题。
- 决策：把跨项目指导沉淀到 `.cursor/skills/agent-design`。Agent Loop 的价值定义为“在可靠工具之间选择下一步”，不是让模型替代领域校验。
- 补充内容：主 skill 增加工具 observation 原则；`agent-loop-runtime.md` 增加工具形状、稳定枚举、`unique/ambiguous/no_match/not_editable` 区分、不可回答状态禁止发澄清；decision framework 和 checklist 增加同类检查项。
- 使用方式：后续设计 agentic 能力时，先定义少量权责清晰的工具和 typed observation，再让模型基于 observation 选择下一步；若工具没有非空授权候选或具体缺失字段，应返回 `no_match/rejected`，不生成空选择题。
