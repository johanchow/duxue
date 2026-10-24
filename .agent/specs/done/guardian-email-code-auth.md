---
slug: guardian-email-code-auth
created: 2026-10-23T23:25:18Z
status: done
---

# Guardian 邮箱验证码注册与登录

## 做什么 / 为什么

按用户 2026-10-24 的新决策，Guardian 完全改为邮箱一次性验证码注册和登录，不再提供密码注册或登录。现有账号均为可丢弃测试数据，无需兼容旧密码或迁移旧账号。邮箱是账号标识，不是独立第二因素。

## 验收标准

- [x] `POST /auth/email-code/send` 接收邮箱，统一返回发送受理结果；服务端以安全随机数生成 6 位数字码，通过已有 `MAIL_*` SMTP 配置发送；不在响应、日志、遥测中输出验证码或 SMTP 凭据。
- [x] 验证码绑定规范化邮箱，短时有效、单次使用；重发使旧码失效；请求和校验都按邮箱及来源限流，连续输错被限制；并发兑换最多成功一次。SMTP 投递失败不留下可兑换码。
- [x] `POST /auth/register` 仅接收姓名、邮箱、验证码，验证成功后创建 Guardian 并发既有 TokenPair；`POST /auth/login` 仅接收邮箱、验证码，已存在 Guardian 验证成功后发 TokenPair。无验证码不能得到登录态；密码请求不再受理。
- [x] Guardian 主键、刷新令牌和 Ward 绑定流程保持有效；数据库迁移删除 Guardian 密码哈希并加入验证码状态。邮件不可用时注册与登录明确失败，不允许绕过。
- [x] Flutter Guardian 登录页完成“邮箱 → 获取验证码 → 注册/登录”；姓名仅注册需要，能处理重发倒计时、过期与限流提示；Ward 入口维持现状。
- [x] 端到端、边界和 App 测试覆盖注册、登录、错误/过期/重放/重发/限流/发送失败；全量 server 和 App 测试及迁移检查通过；PRD、配置模板和技术文档同步。

## 实现计划（Gate 1：计划确认）

1. Server：在 `settings.py` 接入 `MAIL_HOST/PORT/SECURE/USER/PASSWORD/FROM` 并校验组合；封装 SMTP STARTTLS/SSL 发送（连接与读写超时，不泄漏凭据）；新增数据库验证码挑战及迁移。注册与登录都走单次原子兑换，保留现有 TokenPair 和 Guardian 主键。测试数据无需迁移。
2. 安全边界：统一发送响应避免探测账号；验证码只存服务端摘要，不存明文；有效期建议 10 分钟，重发冷却建议 60 秒，单码最多 5 次尝试；邮箱与 IP 的发送频率限制、过期清理和并发兑换测试随实现确定。邮件发送失败须回滚当次挑战。
3. App：更新 API client、`AuthController`、Guardian 登录/注册表单与错误提示；不把验证码长期存本地。更新旧 `/auth/register` 调用的测试夹具及 UI 测试。
4. 文档/交付：把 `docs/product/prd-user.md` 中上轮“保留密码”决策改为邮箱验证码；在 `.env.example` 写入空值示例，说明实际生产环境需同步配置；运行服务端全量 pytest、Flutter test、Alembic check 与 diff review，并在 `.agent/notes/` 记录迁移及 SMTP 接入经验。

## 实现清单

- [x] 服务端测试先复现新契约和安全边界
- [x] 数据模型、迁移、SMTP 与认证接口
- [x] App 界面及客户端测试
- [x] PRD、配置模板、技术文档和笔记
- [x] 全量测试、迁移检查与 diff review

## 备注

- 本地 `duxue-server/.env` 六个 `MAIL_*` 变量均非空，端口为数字，加密值可识别，账号和发件地址形态合理；只做了静态检查，未尝试发信。
- `duxue-server/docker-compose.yml` 通过 `ENV_FILE` 注入变量；生产若用 `.env.prod`，也必须配置同名项。
- 工作区已有 `docs/product/prd-user.md`、`.agent/notes/155-guardian-email-verification-decision.md` 修改，以及与本功能无关的未跟踪 `ddd-layered-map.md`；实现时保留并只改相关文件。
- 验证：Server `pytest tests -q` 633 passed；App `flutter test` 93 passed；改动文件 `flutter analyze` 无问题；SQLite 对新 migration 的旧列/现行表两种形态验证通过；`git diff --check` 通过。完整历史 Alembic 链无法在 SQLite 跑通（旧 migration 使用 PostgreSQL 语法），当前远端开发数据库尚未升级，停在 `20261010_25`。本机 `.env` SMTP TLS/登录成功，未发送实际邮件。
- Gate 2 后续：用户要求同步 `.env.prod`、升级数据库，已完成；明确无需处理旧线上镜像兼容。`duxue-prod` 已到 `20261024_28 (head)`，`alembic check` 无差异；新代码尚未部署。
