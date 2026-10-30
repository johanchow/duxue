---
slug: agent-runtime-contracts
created: 2026-10-30
status: done
---

# Agent 配置目录与运行契约迁移

目标设计与字段契约以 [design-agent.md](../../../docs/technical/design-agent.md) 为准。本期实现本地配置、通用编排与校验，不建设 A/B 或管理台。用户已明确要求开始实现，视为计划确认。

## 验收标准

- [x] `workflows/agents/gates/tools` 是运行配置唯一来源，模型参数、Prompt、工具权限与条件边在文件中可见；独立 API 调用有独立 Workflow。
- [x] JSON Schema 与 Python 契约同时检验；启动拒绝未知字段、引用、处理器、条件、授权扩张及不安全 Gate 路径。
- [x] 通用执行器驱动受控条件边、重试及有序模型尝试；保留答疑、Planning 等现有业务行为与领域边界。
- [x] 流程图与 Trace 来自配置；测试及离线评测覆盖迁移行为。

## 实现步骤

- [x] 提取 Prompt、模型和工具配置，建立分目录 loader、Schema、Python 契约与失败测试。
- [x] 迁移 Workflow 和运行入口；独立调用单独建图，条件 Gate 与模型尝试顺序受执行器约束。
- [x] 更新生成图、文档与决策笔记。
- [x] 运行相关评测、全量测试、静态检查和 diff review。

## 验收卡点

实现与测试完成后交用户验收，再归档和提交。

当前状态：实现完成，用户已要求提交。统一 Agent 结果由运行适配器生成，已有领域 Port 保留兼容解包；模型仍按原候选协议输出。工具与模型循环保持原实现的 3/4 上限与计数方式，字段归属和作用范围补入设计文档。本次测试 696 项通过，配置/生成图/静态检查通过，评测数据集 76 个单轮用例和 2 个多轮用例校验通过，离线重放逻辑随全量测试验证；未执行真实模型 API 评测。

## 历史迁移记录（以下未完成项已由上述当前状态取代）

已迁入 10 个模型单元（主备模型合并）、2 个代码 Gate、4 个 Tool、7 个 Workflow；固定与动态 Prompt 正文均以 JSON 为源。模型调用双层验证，任务整理、复盘维度及答疑审核已使用通用执行器。主路由、Planning 确认恢复及答疑重试外层仍有旧节点类型；Context Builder 尚未从调用方迁至注册执行，因此验收项保持未完成。答疑 Judge 由并行改为按条件顺序执行，文字拒绝时跳过配图 Judge；可见输出保持现有回退规则，受保护文字通过后配图审核的延迟可能增加。

后续进展：新增 `tutoring-retry` Workflow；Companion 主路由、答疑重试/主备切换已接入通用执行器。Planning 将等待确认与确认门禁拆为独立 Graph 节点，恢复时不重复写入草稿。全部 10 个模型单元的 Context Builder 已注册执行，并限制各单元可绑定的构造器范围。全量测试 684 项通过。尚需清理旧 Workflow 节点类别、统一 Judge 裁决协议与代码 Agent 契约，并补齐全目录处理器/条件启动校验；这些未完成前不能标记整体迁移完成。

本轮补齐：节点类型收敛为 agent/gate/action；handler_id/condition_id 对齐目标字段；Trace 类别独立于节点概念。Judge 增加 provider_output_schema 与标准裁决适配，代码 Agent 使用真实 RunInvocation/WorkflowOutcome Schema 并在 Dispatcher 双层校验。新增代码注册表，启动检查所有 Workflow 处理器与条件。687 项测试通过，评测数据集 76 cases + 2 episodes 校验通过（没有执行真实模型评测）。仍需统一 Agent status/data/error_code 封套，以及把实现内部的校验/工具循环预算全部纳入目标运行契约；完整验收项保持未勾选，避免把结构迁移等同于完整执行协议迁移。
