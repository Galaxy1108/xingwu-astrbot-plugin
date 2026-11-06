"""Email delivery for OTP codes.

Production: SMTP (``SAAS_SMTP_*`` env or plugin config). Development / tests:
codes are logged and kept in memory (``dev_code`` is also echoed by the API when
``otp_dev_echo`` is on). Never log the code in production mode.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Protocol

from .config import Settings

logger = logging.getLogger(__name__)


class Mailer(Protocol):
    def send_otp(self, to: str, code: str, *, expires_minutes: int) -> bool: ...


@dataclass
class LogMailer:
    """Dev fallback: keep codes in memory for tests and log a warning."""

    sent: list[dict[str, Any]] = field(default_factory=list)

    def send_otp(self, to: str, code: str, *, expires_minutes: int) -> bool:
        self.sent.append({"to": to, "code": code, "expires_minutes": expires_minutes})
        logger.warning(
            "未配置 SMTP：验证码仅记录在本地（收件人 %s，%s 分钟内有效）。"
            "生产请配置 SAAS_SMTP_HOST 等环境变量。",
            to,
            expires_minutes,
        )
        return False


@dataclass
class SmtpMailer:
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = "no-reply@localhost"
    from_name: str = "AstrBot 控制台"
    starttls: bool = True
    use_ssl: bool = False
    timeout: int = 15

    def _message(self, to: str, code: str, expires_minutes: int) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((self.from_name, self.from_addr))
        message["To"] = to
        message["Subject"] = f"登录验证码：{code}"
        message.set_content(
            f"你的登录验证码是：{code}\n\n"
            f"有效期 {expires_minutes} 分钟，仅可使用一次。\n"
            "如非本人操作，请忽略本邮件。\n"
        )
        return message

    def send_otp(self, to: str, code: str, *, expires_minutes: int) -> bool:
        message = self._message(to, code, expires_minutes)
        if self.use_ssl:
            smtp = smtplib.SMTP_SSL(
                self.host,
                self.port,
                timeout=self.timeout,
                context=ssl.create_default_context(),
            )
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        try:
            smtp.ehlo()
            if self.starttls and not self.use_ssl:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)
        finally:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001
                pass
        return True


def build_mailer(settings: Settings) -> Mailer:
    if settings.smtp_host:
        return SmtpMailer(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            from_addr=settings.smtp_from or settings.smtp_user or "no-reply@localhost",
            from_name=settings.smtp_from_name,
            starttls=settings.smtp_starttls,
            use_ssl=settings.smtp_ssl,
        )
    return LogMailer()
