# Guardian 邮箱认证决策（2026-10-24）

- 现状：`POST /auth/register` 接受邮箱和密码后直接创建 Guardian 并发令牌，未验证邮箱归属；App 只有邮箱密码入口。`docs/product/prd-user.md` 原先写用户名密码和微信、排除邮箱验证码，与代码不一致。
- 决策：Guardian 保留邮箱 + 密码登录，注册、邮箱变更及受控找回使用邮件一次性确认码。邮箱未验证前不发可访问 Ward 数据的登录态。邮件确认码不是独立日常登录方式或第二因素；依据 NIST SP 800-63B 对邮箱确认码与邮箱带外认证的区分。
- 实现边界：读学服务端生成、存储校验状态、限时与单次消费确认码并限流；邮件推送服务只负责发送。阿里云 Direct Mail 可用 SingleSendMail 的 `TextBody`/`HtmlBody`，或经确认可用的模板参数传入服务端生成的确认码。微信登录须等待移动应用资质与权限核实，已有账号通过已登录态主动绑定，不能按昵称或邮箱自动合并。
- 本次仅更新产品决策文档；服务端、App 和数据库尚未实现邮箱验证，文档明确标注了现状。
- 同步把 PRD 中 Ward 的用户名/微信登录和 4 位绑定码改成当前 6 位绑定码入口，避免认证章节自相矛盾。
- 依据：[NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html)、[OWASP 邮箱验证指南](https://cheatsheetseries.owasp.org/cheatsheets/Email_Validation_and_Verification_Cheat_Sheet.html)、[阿里云 SingleSendMail](https://help.aliyun.com/zh/direct-mail/api-dm-2015-11-23-singlesendmail)、[阿里云发信配置](https://help.aliyun.com/zh/direct-mail/getting-started/simplified-procedure-of-configuring-email-delivery)。
