---
slug: mentor-courseware-save
created: 2026-11-27T05:07:34Z
status: draft
---

# 成人主动保存课件

交付范围见 [PRD §7.2](../../docs/product/prd-user.md#72-家长问答体验) 和 [Tutoring 课件专题](../../docs/technical/topic-mentor-courseware.md)。

## 验收标准

- [x] 从真实问答入口生成未保存课件，列表为空；保存并清空对话、重登后可打开同一 ID、原题及动态步骤。
- [x] 临时输入资源过期后已保存版本仍可渲染；保存失败可重试，同一请求回执丢失不会重复创建。
- [x] 重开后当前版本、Undo/Redo、成功修订和改名均保留；失败修订不覆盖旧版。
- [x] 保存与修订/过期并发受版本检查保护；删除与迟到写入竞争不会复活课件。账号间不可列出或读取。
- [x] 数据迁移前备份，记录测试业务库实际 revision、两表约束与索引，验证业务写读。

## 实现计划与检查清单（Gate 1）

- [x] 在 tutoring/domain/mentor_courseware.py 增加保留状态及命令行为；扩展 commands、queries、ports 和对应领域/命令测试。
- [x] 在 infrastructure/persistence、ORM 与 migrations/versions 增加专题 §6.2 的聚合存储、版本唯一约束、列表和到期索引。用 PostgreSQL 检查 CAS、并发与迁移，覆盖旧临时实例的兼容窗口。
- [x] 在成人课件应用服务及 storage 适配器实现私有素材长期引用、失败重试与无引用清理；在 guardian_courseware API 加保存/列表/改名/删除及鉴权回归。
- [x] 在 Flutter API client、GuardianQuestionPage 与课件页接入保存提示、列表和同 ID 重开，覆盖跨账号、重登和修订控件的组件测试。
- [x] 跑服务端及 Flutter 回归、静态检查。备份 .env 实际业务测试库后迁移，回读 revision、表结构，使用隔离测试身份走保存至删除全链路，再交 Gate 2 验收。

## 联调基线

2026-11-27 直接使用 duxue-server/.env 只读查询 PostgreSQL，current_database() 为 duxue-test，alembic_version 为 20261121_40，两张目标表均不存在。实施迁移前须重新核实。


## Gate 2 验收证据

- 测试库 duxue-test 从 20261121_40 升至 20261127_41 (head)。已验证备份目录清单、主键、索引、版本外键与隔离测试数据写读删除。备份位于 ignored 的 duxue-server/var/backups/courseware-1795756417.dump。
- 服务端全量 1600 passed、4 skipped、3 subtests passed。后续新增/调整的保存 API、图片及一次性 PostgreSQL 集成回归 6 passed。一次性 PostgreSQL 使用同一 postgresql@14 的 initdb、postgres 和 pg_ctl。Flutter 全量 198 passed，analyze 无问题。
- Android 2211133C：已登录成人从问答提交正方体表面最短路，生成 v1 并保存，强制结束 App 后从我的课件找到同一条，显示 √5 与 3D 步骤。更新客户端和重启服务后再次打开成功。真机使用现有登录状态，未退出用户账号。修订/撤销/重做及权限隔离用独立数据库/API 用例验证；题图保留由快照测试验证。
- 调试包访问 USB 转发的 8038 本机服务。待用户 Gate 2 体验验收。
