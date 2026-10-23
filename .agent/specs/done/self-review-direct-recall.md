---
slug: self-review-direct-recall
created: 2026-10-23T01:21:25Z
status: done
---

# self-review-direct-recall spec

## 做什么 / 为什么
Ward 用语音或文字表达今日总结，AI 提出可编辑的六维条目；原话和 Ward 确认后的整理由 Evaluation 保存。近期召回直接查询 Evaluation，不经 Memory 建立总结副本。`long_term_profiles` 保持现状。

## 验收标准
- [x] Ward 可以提交自然语言总结、检查并修改候选条目；未表达的维度留空，原话和版本可追溯。
- [x] Ward 的总结查询只返回当前确认版本，按日期/任务/主题与用途限量；跨 Ward 和 Guardian 原话读取拒绝。
- [x] 答疑/计划仅在相关请求需要时接入自述上下文，标明自述来源；不自动生成计划或长期结论。
- [x] 不再新发布 `self_review.submitted`，旧 Memory 事实保留既有删除/审计处理；没有 `daily_review` Episode。
- [x] 测试覆盖提交、修订、授权、召回、模型失败和旧兼容路径；服务端测试和 App 分析通过。

## 实现计划（Gate 1：用户已在本次会话确认设计并明确要求改代码）
- 影响文件：Evaluation 的 ORM/迁移、应用服务、REST schema/路由、反思工作流；App 总结入口；Companion 上下文组装与答疑/计划接入；对应设计文档。
- 测试计划：先写关键失败测试，再分步实现；运行相关 pytest、全量 pytest、Flutter analyze 和迁移校验。
- 约束：不修改 `long_term_profiles`；不凭正则判断开放语义；不将自述自动提升为掌握证据。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] Evaluation 版本化原话与六维条目持久化及迁移
- [x] 自由表达、候选整理、Ward 确认/修订与 App 入口
- [x] 受权近期总结查询及按需模型上下文
- [x] 移除旧总结事实新投递，保持历史清理兼容
- [x] 测试、文档一致性和审查

## 备注
全量服务端 624 passed；Flutter test 全绿，Flutter analyze 无问题；新迁移的 fresh/incremental 分支由隔离测试覆盖。现有数据库的 `alembic check` 因未升级到 head 不能运行；从空 SQLite 执行完整迁移链在既有 `20260926_20` 的 `ALTER COLUMN` 处失败，与本次迁移无关。用户已在 2026-10-23 请求 commit，视为 Gate 2 验收。
