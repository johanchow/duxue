---
slug: remove-tenant-add-grade-and-chat-input
created: 2026-08-23T00:00:00Z
status: draft
---

# remove-tenant-add-grade-and-chat-input spec

## 做什么 / 为什么

将系统从遗留的多租户数据模型迁移为家庭直连模型：删除 `tenants` 表及全部 `tenant_id` 字段、JWT claim 和鉴权分支；新增 Ward 学段字段；把 Guardian 传递作业入口改为微信式对话输入与附件菜单。

## 验收标准

- [x] Alembic 迁移可升级/回滚：删除全库 `tenant_id` 和 `tenants`，新增 `user_wards.grade_stage`；现有单租户数据保留并迁移成功。
- [x] 服务端模型、JWT、依赖注入、任务与报告管道不再引用 tenant；Guardian 仅能通过 `guardian_ward_relations` 操作关联 Ward，Ward 只能操作自己。
- [x] 创建 Ward API 接受并返回 `grade_stage`（小学/初中/高中），服务端校验非法值。
- [x] App 新增孩子时必须选择学段，列表/详情展示学段；模型和 API 契约同步更新。
- [x] 传递 sheet 使用底部微信式文字输入栏和「+」附件菜单，附件菜单提供语音/截图入口；文字仍能向所选多个 Ward 创建任务。
- [x] 服务端与 Flutter 测试、静态检查均通过；已配置数据库成功升级至 head 后再报告。

## 实现计划（Gate 1：用户已于 2026-08-23 确认去租户化范围）

- 影响文件：`duxue-server/app/{models,main,dependencies,schemas,security,services}.py`、`infrastructure/messaging/celery_tasks.py`、新增 Alembic 迁移和测试；`duxue-app/lib/{core,features}`、测试和决策笔记。
- 实施顺序：先服务端模型/鉴权/迁移与测试，后 App API/年级/UI，最后在已配置数据库运行迁移、执行全量测试并审查 diff。
- 测试计划：Alembic upgrade/downgrade 与服务端 unittest；`flutter analyze`、`flutter test`；手动检查传递文字提交与附件菜单。

## 实现清单

- [x] 去除服务端租户模型与鉴权依赖
- [x] 新增年级字段及 API 契约
- [x] 编写并验证数据库迁移
- [x] 更新 App 年级与微信式传递 UI
- [x] 运行测试、记录决策并等待验收
