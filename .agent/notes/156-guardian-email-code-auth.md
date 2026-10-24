# Guardian 邮箱验证码注册与登录（2026-10-24）

- 用户明确改为邮箱验证码注册与日常登录，取消读学密码；原 `155-guardian-email-verification-decision.md` 的“保留密码”结论被本次决策取代。现有 Guardian 均为测试数据，无需账号迁移。
- 服务端新增 `/auth/email-code/send`，用 `MAIL_*` SMTP 参数发信。验证码使用安全随机数生成 6 位数字，只存基于 `JWT_SECRET_KEY` 的 HMAC 摘要；10 分钟有效，单次使用，重发使旧码失效。按邮箱 60 秒冷却及 5 次/小时、来源 20 次/小时限制发送；每码最多 5 次校验。PostgreSQL 用事务级 advisory lock 串行同邮箱发送/兑换。
- SMTP 发送前挑战仍在事务中；发送失败回滚，接口统一返回 503 且不回显服务商异常。邮件服务确认接收不代表最终投递成功。线上还需确认发件域名、SMTP 授权以及收件箱送达。
- 删除 `user_guardians.password_hash`，通过新 Alembic 迁移升级。历史空库重建 migration 会用当前 ORM 创建表，因此新 migration 必须检测表/列是否已经存在，避免重复建表或删列失败。
- Flutter Guardian 表单改为邮箱和验证码；Ward 绑定入口保持原样。当前 App 与 Server 仅改本地代码，没有执行数据库升级或向真实邮箱发测试邮件。
- 本机 `.env` 静态检查显示六项 SMTP 参数完整且 SSL/端口匹配；随后进行不发邮件的 TLS 连接与 SMTP 登录，成功。阿里云是否接受此发件地址以及最终送达需真实邮件验证。当前本地数据库停在 Alembic `20261010_25`，未执行迁移；旧版迁移链不能完整在 SQLite 跑通，新增 revision 对“旧密码列”和“历史空库重建后的现行表”两种形态分别做了隔离测试。
- 2026-10-24：用户授权升级数据库及同步生产配置。本地 `.env` 指向 `duxue-test`，本地与 ECS `/home/duxue/duxue-server/.env.prod` 指向 `duxue-prod`；确认两份生产配置原先非邮件变量一致后，把六项 `MAIL_*` 从本地 `.env` 同步到本地与 ECS `.env.prod`。ECS 原配置备份为 `.env.prod.backup-1792803407712`，新文件权限 0600；两份生产配置哈希一致，下载的本地临时副本已清理。生产数据库从 `20261023_27` 升至 `20261024_28 (head)`，`alembic check` 为 `No new upgrade operations detected`。
- 用户明确线上全是测试用户，不处理旧镜像与新数据库的临时兼容，也不需要为兼容增加实现复杂度。本次未部署 Server/App 新代码；新认证流程需后续代码部署后在线生效。
