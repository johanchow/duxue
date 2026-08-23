# 去租户化、学段与传递输入

- 数据权限的唯一入口是 `guardian_ward_relations`：Guardian 对 Ward 资源先校验关联；Ward JWT 只允许路径中的自身 `ward_id`。设备、帧、报告、计划与自评都通过所属 Ward 间接受该规则保护。
- 新迁移 `20260823_04` 在 PostgreSQL 直接删除旧外键、索引、联合唯一约束和 `tenant_id` 列；在 SQLite 测试环境使用 batch 模式。报告、计划与自评的唯一约束改为 `(ward_id, date)`，并给 `user_wards` 增加非空、默认 `primary` 的 `grade_stage`。
- 传递入口保留纯文字真实创建任务的路径；语音和截图仅为明确的 UI 接口位，在上传契约落地前不伪造任务。
- 验证：SQLite 迁移 `upgrade → downgrade → upgrade` 成功；配置数据库已升至 `20260823_04 (head)`；后端 pytest 21 项、Flutter analyze 和 5 项测试均通过。配置的公网 API 健康请求返回 HTTP 502，需由部署侧恢复后再做外网 HTTP 冒烟。
