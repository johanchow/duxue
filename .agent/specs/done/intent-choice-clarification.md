---
slug: intent-choice-clarification
created: 2026-10-22T02:37:37Z
status: done
---

# intent-choice-clarification spec

## 做什么 / 为什么
当意图模型返回 `unclear`，给 Ward 三个可点击选项；点击后以服务端保存的原输入进入所选场景。

## 验收标准
- [x] `unclear` 返回 `intent_choice` 交互，选项为管理任务、总结思考、提问探讨，并保存在当前回复的 transcript 引用中；普通文本澄清不建 Run。
- [x] 选择动作绑定当前 Thread 版本、待澄清回复和原输入；重放、过期、伪造选项返回 409；有效选择只 dispatch 一次原输入，保留原附件。
- [x] App 当前消息显示三个选项；点击发送服务端签发动作，历史或过期选项不可点击，刷新后仍可显示当前选项。
- [x] 服务端和 Flutter 测试覆盖正常点击及过期动作；文档、笔记与代码一致。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 用户本轮已明确要求实现点选澄清，视为本计划的实现授权。
- 影响文件：Coordinator、Turn Schema、Companion 交互设计、Ward 聊天页与测试。
- 实现：`unclear` 回复写入受控 `intent_choice` 引用；`choose_intent` 从当前回复引用和原 Ward 消息校验并恢复业务输入。App 从 transcript 渲染选项并提交动作。
- 测试计划：服务端状态/授权/重放测试、Flutter 点选和恢复测试、全量 pytest 与 Flutter test/analyze。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 阅读协议和当前 UI / 路由链路
- [x] 服务端交互与受控选择
- [x] App 选项展示与点击
- [x] 全量验证、diff review、决策笔记

## 备注
