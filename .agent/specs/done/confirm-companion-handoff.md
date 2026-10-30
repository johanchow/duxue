---
slug: confirm-companion-handoff
created: 2026-10-29T23:50:03Z
status: done
---

# 跨场景切换独立确认

## 做什么 / 为什么
修复 trace `82e3ab30801d39d3b625afbb8c823173` 中答疑续接被误切到 Reflection：已有 focus 时，意图模型的异场景提议必须经独立模型确认。

## 验收标准
- [x] 无 focus、同场景续接、安全与已验证 UI 指令维持原路径，不增加确认调用。
- [x] 有 focus 且模型提出另一业务场景时，独立组件依据本轮输入和已授权会话窗口确认；允许才 handoff，否决、异常或非法输出均继续原 focus。
- [x] 原始误路由会话回归为 `tutoring/continue`；明确要求换场景仍可 handoff。
- [x] 路由与判断结果可在遥测中区分，文档和测试与实现同步。

## 实现计划
- 影响文件：Companion Coordinator/Router/Ports、AI 组件与提示词、相关单元和应用测试、`domain-companion.md`、决策笔记。
- 测试计划：先写失败用例覆盖否决、允许、判断失败、无需判断；再实现并跑服务端全量测试与静态检查。
- Gate 1：用户已明确要求实现此前提出的“建议 2”（独立切换确认），本计划按该授权执行。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 建立 spec、核对设计与现有链路
- [x] 失败测试覆盖切换门槛与真实会话
- [x] 实现独立模型组件和 fail-closed 路由
- [x] 更新设计文档和决策笔记
- [x] 全量测试、静态检查、diff review

## 备注

场景定义只在 [`docs/technical/domain-companion.md`](../../../docs/technical/domain-companion.md) 维护，本 spec 仅记录此次验收和计划。
