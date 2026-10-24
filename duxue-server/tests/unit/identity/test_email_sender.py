from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.infrastructure.messaging.email import send_email_code


def test_smtp_ssl_and_starttls_use_credentials_and_send_code():
    for secure, class_name in ((True, "SMTP_SSL"), (False, "SMTP")):
        config = SimpleNamespace(
            mail_host="smtp.example.com",
            mail_port=465 if secure else 587,
            mail_secure=secure,
            mail_user="sender@example.com",
            mail_password="test-secret",
            mail_from="sender@example.com",
        )
        transport = MagicMock()
        transport.__enter__.return_value = transport
        with patch("app.infrastructure.messaging.email.settings", config), patch(
            f"app.infrastructure.messaging.email.smtplib.{class_name}", return_value=transport
        ):
            send_email_code(recipient="parent@example.com", code="123456")
        if secure:
            transport.starttls.assert_not_called()
        else:
            transport.starttls.assert_called_once()
        transport.login.assert_called_once_with("sender@example.com", "test-secret")
        message = transport.send_message.call_args.args[0]
        assert message["To"] == "parent@example.com"
        assert "123456" in message.get_content()
