# 退役默认锦囊与今日总结领域边界

日期：2026-10-22

- 决策：当前阶段不自动生成默认“专注锦囊”，不提供采纳标记或将建议写入计划。Ward 自己说的下次意向仍可作为自述保存，不能等同于系统建议。
- 清理：REST 提交、Companion Reflection Workflow、请求字段、界面建议展示与 `reflection.advice` 组件不再使用 `FocusKit`；前向迁移删除 `focus_kits`。旧 `focus_kit.adopted` 只可能留在历史证据账本，不再生产。
- 迁移坑：历史 `20260830_10` 空库重建使用**当前** ORM metadata，新库运行到新迁移时可能已经没有 `focus_kits`；删除操作需检查表是否存在。降级可恢复空表结构，但不能恢复原行。
- 领域设计：`SelfReview` 保存 Ward 原话与确认的整理条目；六维是可缺省的分类值，不是六个固定文本列。提示从当天任务、问答主题与用时事实生成；主客观信息分轨呈现，确认后才向 Memory 发自述事实。报告按证据版本追加。
- 实施差距：现有 `self_reviews` 仍只有 `feeling/reflection/timeline_json/version`，开放表达、`self_review_aspects`、确认交互和版本化报告为后续目标；技术设计明确区分现状与目标。
- 验证：服务端全量 pytest 617 passed；迁移测试覆盖有表/无表；Flutter 静态分析通过。真实数据库 `alembic current` 为 `20261010_25`，新迁移 `20261022_26` 尚未执行，因此 `alembic check` 报 target database is not up to date；未对真实数据库执行删表。
