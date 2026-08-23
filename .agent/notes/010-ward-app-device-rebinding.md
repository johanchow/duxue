# Ward App 安全换机绑定（已被纯绑定码方案取代）

> 该 PIN 方案已于 2026-08-23 被“6 位一次性绑定码，无 PIN”取代；最终规则见 `012-ward-app-six-digit-binding.md`。

- Ward 的物理 App 不单独存档；用 `ward_credentials.session_version` 表示当前有效会话代次。Ward JWT 带同名 claim，依赖层与数据库版本比对；成功换机递增版本，因此旧 Ward App token 立即失效。
- 首次用绑定码时创建 PIN 和版本 0；已有凭据时绑定码只允许验证既有 PIN，错误 PIN 不消费邀请码、不改变 PIN。旧 JWT 未携带版本时按 0 兼容，部署不会强制所有既有学生下线；第一次成功换机后它自然失效。
- Guardian 生成码入口位于 Ward 详情的“设置 → 绑定/更换学生 App 设备”。码仍是 10 分钟一次性且经过 `guardian_ward_relations` 校验；不再把学生设备绑定混在“今晚学习故事”中。
