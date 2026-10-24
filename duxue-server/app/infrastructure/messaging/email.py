"""Send a single transactional email with the server's SMTP account."""

import smtplib
import ssl
from email.message import EmailMessage

from app.bootstrap.settings import settings


class MailConfigurationError(RuntimeError):
    pass


def send_email_code(*, recipient: str, code: str) -> None:
    if not all((settings.mail_host, settings.mail_port, settings.mail_user, settings.mail_password, settings.mail_from)):
        raise MailConfigurationError("SMTP is not configured")
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = recipient
    message["Subject"] = "读学登录验证码"
    message.set_content(f"您的读学验证码是 {code}，10 分钟内有效。若非本人操作，请忽略此邮件。")
    context = ssl.create_default_context()
    if settings.mail_secure:
        with smtplib.SMTP_SSL(settings.mail_host, settings.mail_port, timeout=10, context=context) as smtp:
            smtp.login(settings.mail_user, settings.mail_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings.mail_host, settings.mail_port, timeout=10) as smtp:
            smtp.starttls(context=context)
            smtp.login(settings.mail_user, settings.mail_password)
            smtp.send_message(message)
