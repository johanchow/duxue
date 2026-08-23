# Ward App 纯 6 位绑定码

- Ward 学生端不存在独立 PIN、Ward ID 登录或密码登录。首次绑定和换机完全一致：Guardian 为已关联 Ward 生成 6 位数字码，学生端在 10 分钟内输入一次即登录。
- 绑定码由 `secrets.randbelow` 生成，服务端检查全表唯一性；`ward_invites.code` 保持一次性语义。码成功使用后，`session_version` 递增（首次为 0），所有旧 Ward JWT 立即失效。
- `ward_credentials` 只保留会话版本，迁移 `20260823_06` 删除废弃 `pin_hash`；`/ward-auth/login` 与 Flutter `wardLogin` 一并删除，避免留下绕过 Guardian 授权的入口。
