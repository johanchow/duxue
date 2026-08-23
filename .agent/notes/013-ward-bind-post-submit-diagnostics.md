# 学生绑定成功后的本地失败诊断

- 现象：服务端 `POST /ward-auth/bind` 返回 200，但学生端仍显示“绑定失败”，并出现 `Navigator.pushReplacement` 的 `_RouteEntry.complete` 断言。
- 根因：绑定页把 GoRouter 管理的页面用 `Navigator.pushReplacement` 作命令式替换；此外 App 只用布尔值表示已登录，无法区分 Ward token 与 Guardian token，学生会话会落入 Guardian 路由和 refresh-token 流程。
- 规避：学生页成为 GoRouter 的正式 `/ward-day/:wardId` 路由；会话显式携带 Ward ID，路由只允许该 Ward 的学习空间；Ward token 遇到 401 原样返回，不尝试 Guardian refresh token。仍保留绑定后异常的安全诊断日志，不输出 token 或请求头。
