---
slug: ward-app-device-rebinding
created: 2026-08-23T07:51:53Z
status: draft
---

# ward-app-device-rebinding spec

## 做什么 / 为什么
让 Guardian 在 Ward 详情的设置页为 Ward 学生端 App 绑定或更换设备：首次与换机完全一致，只输入一个 6 位数字绑定码；码一次性、10 分钟有效，成功后同一 Ward 的旧 App 会话立刻失效。

## 验收标准
- [x] Guardian 可在 Ward 详情「设置」生成 6 位数字 Ward App 绑定码；码为一次性、10 分钟有效，且仅能给自己关联的 Ward 生成。旧「今晚学习故事」页面不再承载该入口。
- [x] Ward 新设备绑定页只有一个 6 位数字码输入框，无 PIN、Ward ID 或其他登录入口；首次绑定与换机交互完全一致。
- [x] 成功绑定或重新绑定后，当前 Ward App 获得新 token；此前 Ward App token 立即被服务端拒绝。Guardian token、摄像设备 token 与其他 Ward 不受影响。
- [x] 删除 Ward PIN 与 PIN 登录 API；迁移保留会话版本但删除 `pin_hash`，所有 Ward-only 及 Ward/Guardian 共享的 Ward token 路径都校验会话版本。
- [x] 后端 HTTP 测试覆盖 6 位格式、一次性/过期、旧 token 失效及 Guardian 越权；Flutter 静态分析、测试与 Android Debug 构建通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  - `duxue-server/app/{models,security,dependencies,main,schemas}.py`：Ward JWT 保留 `ward_session_version` 声明与数据库比对。`/ward-auth/bind` 只接受 6 位数字一次性码，成功即递增会话版本、消费邀请码并签发新 token；删除 PIN 登录。
  - `duxue-server/migrations/versions/`（新增）：删除 `ward_credentials.pin_hash`，保留会话版本，提供 downgrade。
  - `duxue-app/lib/features/{ward_pages,day_story_pages}.dart` 与 `core/api_client.dart`：Guardian 弹窗显示 6 位码；绑定页只保留绑定码；移除 PIN 参数和 Ward PIN 登录方法。
  - `duxue-server/tests/`、`duxue-app/test/` 和 `.agent/notes/`：覆盖会话撤销与 UI 入口，记录安全边界。
- 会话撤销方式：不保存物理设备或刷新 token；使用每个 Ward 的单调 `session_version`。每次成功绑定递增版本，所有旧 Ward JWT 的版本不匹配而立即失效。该版本只用于 Ward JWT，不影响 Guardian 或 Device JWT。
- 测试计划：先写后端失败测试，证明只允许 6 位码、邀请码一次性、Guardian 不能签发他人 Ward、旧 Ward token 在再次绑定后收到 401；再做最小实现。最后跑迁移 upgrade/downgrade、后端 pytest、Flutter analyze/test、Debug APK。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 数据模型、迁移与 Ward token 版本校验
- [x] 绑定/换机 API 与安全测试
- [x] Guardian 设置入口与 Ward 绑定文案
- [x] 全量验证与决策沉淀

## 备注
- 不记录物理设备指纹或 PIN；“换机”语义是替换当前 Ward App 会话。新设备成功绑定后旧设备不能继续请求，若其保留 App 数据也无法与服务端交互。
