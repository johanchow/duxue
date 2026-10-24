# Guardian 登录 404 与 App 提示（2026-10-24）

- Grafana Tempo 测试环境 Trace `4d0ba0cf2985bf4d51bee56633481733`：09:10:55（北京时间）`POST /auth/email-code/send` 返回 202，向 `duxue-test` 写入验证码挑战。
- Trace `d559eef992a085c20c7b6f60f697c274`：09:11:21 `POST /auth/login` 返回 404；链路先更新挑战为已消费，再查询 `user_guardians`。按接口实现，验证码校验通过后找不到 Guardian 才返回 `account not found`；事务回滚令该验证码仍可用于注册。Trace 不含邮箱或验证码明文，无法从中确认用户输入的邮箱，但能确定这次请求查询的是 `duxue-test`。未发现 SMTP 或数据库异常。
- App 原本将 404 映射成短暂 Snackbar，但 `routerProvider` 使用 `ref.watch(authProvider)`，登录开始时状态改为 `AsyncLoading` 导致路由实例重建，登录页可能被卸载；异常处理检查 `mounted` 后便不展示提示。
- 修复：路由实例保持稳定，通过 `ValueNotifier` 刷新重定向；只有 `/auth/login` 返回 404 且响应 `detail=account not found` 时才持续展示“该邮箱尚未注册，请先注册”和“去注册”入口。切换后保留邮箱、验证码；其他接口的 404 提示服务不可用，避免误导。
- 回归：整 App 路由下未知 Guardian 登录的界面测试先红后绿；服务端补测试锁定有效验证码登录未注册邮箱为 404，随后同码可注册。完整 Server 634 例和 App 94 例通过。
