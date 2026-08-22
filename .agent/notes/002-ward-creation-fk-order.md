# Ward 创建的 PostgreSQL 外键顺序

- 现象：`POST /wards` 在 PostgreSQL 报 `guardian_ward_relations_ward_id_fkey`，而 SQLite 测试未暴露。
- 根因：`Ward` 与 `GuardianWard` 没有关联映射，SQLAlchemy 不能推导二者 insert 顺序；首次 flush 只写入 `users`，提交时可能先写关联表。
- 修复：`db.add(ward)` 后显式 `db.flush()`，再添加 Guardian-Ward 关系。
- 回归：`tests/test_ward_creation.py` 用记录调用顺序的 Session 替身，要求第二次 flush 出现在关联写入之前；与 e2e 测试一起通过。
