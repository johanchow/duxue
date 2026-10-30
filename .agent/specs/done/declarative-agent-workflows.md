---
slug: declarative-agent-workflows
created: 2026-10-30T01:48:10Z
status: done
---

# 统一 Agent 流程定义与可视化

## 做什么 / 为什么
将 Companion 路由、Planning、Tutoring、Reflection 的流程结构收敛到 `duxue-server/agent_specs/`。运行时读取同一份定义来装配/校验流程，文档从定义生成；保留 Python 节点实现和领域安全裁决。

## 验收标准
- [x] 四类 Agent 在同一目录各有版本化结构定义，包含节点、业务调用/Prompt 引用、工具、门禁和实际条件边；定义可被 Schema 验证，错误引用/连线/缺失必经门禁启动失败。
- [x] Companion 分发与 Planning Graph 从定义装配；Tutoring、Reflection 的实际步骤在运行时使用定义中的节点身份并核对必需步骤，不让配置绕过授权、答案保护和事务。
- [x] 组件/Prompt、工具与流程关系可从单个目录入口浏览；图从同一配置生成，CI 验证图无漂移。
- [x] 每个业务 span 标注流程 ID/版本与节点 ID；现有 Langfuse/Grafana 链路、生产行为及失败回退保持兼容。
- [x] 关键路径和错误配置有回归测试，服务端全量测试通过，技术设计同步更新。

## 实现计划

- 定义层：新建 `agent_specs/*.json`、Pydantic loader 与校验器。节点声明 `id/kind/handler/component/required`；有向边声明受限的条件 ID，不能包含任意代码。组件 ID 与代码 Registry 校验，Prompt 从该 Registry 解引用。工具声明与代码实现集合互校验。
- 运行层：Companion dispatcher 通过定义选目标处理器；Planning Graph 从定义创建节点/边；Tutoring/Reflection 的显式步骤从定义解析节点 ID，受保护门禁在代码中强制执行并由配置验证为必需。每个业务 span 统一附加流程版本。
- 可视化：提供 `python -m app.agent_specs export`，生成独立的 `docs/technical/agent-flow-current.md`；`design-agent.md` 只记录目标方案、类型契约与目录规范，测试检查生成图和定义一致。
- 影响文件：上述目录与 loader、Coordinator/Dispatcher、Planning/Tutoring/Reflection、遥测、工具、AI Registry、技术设计、单元/集成测试和 `.agent/notes/`。
- 测试计划：先写配置失效与图漂移失败测试，再小步迁移；跑服务端全量 pytest、相关 Ruff、`git diff --check`，最后 review diff。
- Gate 1：用户已明确接受上轮提出的结构化定义方案并要求实现，本计划按该授权执行。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 建立 spec，盘点现有流程与约束
- [x] Schema、定义和错误配置测试
- [x] 运行时从定义装配/校验四类流程
- [x] 目录索引与生成流程图
- [x] 文档与决策笔记
- [x] 全量测试、静态检查与 diff review

## 备注

- Gate 2：实现与测试已完成，用户已要求提交，spec 已归档。
