---
slug: ward-session-refresh
created: 2026-09-13T00:00:00Z
status: draft
---

# Ward 会话续期

## 做什么 / 为什么
Ward 登录目前只保存 15 分钟 access token，导致重启或停留一段时间后出现 401，且语音 WebSocket 无法共用刷新机制。本改动为 Ward 增加可轮换、受 session_version 约束的 refresh token，并让 App 统一恢复和刷新会话。

## 验收标准
- [ ] Ward 绑定响应同时返回 access/refresh token；refresh token 只能用于对应 Ward 的当前 session_version，重绑后旧 access 和 refresh 都失效。
- [ ] App 安装后保存 Ward refresh token；启动时刷新恢复，REST 401 自动刷新一次并重试，语音开始前会在 access 即将过期时刷新。
- [ ] refresh 失败会清除本地会话并回到登录/绑定入口；遥测记录结果但不含 token。
- [ ] 服务端迁移、服务端测试及 Flutter 测试/静态检查通过。

## 实现计划（已获用户确认）
- 服务端新增 Ward refresh token 表、签发/轮换 endpoint，并在重绑及数据删除时撤销或清理 token。
- Flutter 扩展安全存储和 ApiClient 的集中刷新能力，AuthController 在启动时恢复会话；以通用 prop 在录音前运行会话预检。
- 增加 rebind/refresh 回归测试，执行格式化、测试和检查，记录决策。

## 实现清单
- [x] 服务端 token 模型、迁移与路由
- [x] App 会话恢复、401 重试和语音预检
- [x] 自动化测试与静态检查
- [x] 记录决策
