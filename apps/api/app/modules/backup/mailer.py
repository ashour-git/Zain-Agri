"""Sending email through a dedicated Gmail account (SMTP + app password).

Free, no domain needed (spec 2026-11-12 §4). ``Mailer`` is a protocol so tests
record messages instead of sending them.
"""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Annotated, Protocol

from fastapi import Depends

from app.core.config import Settings, get_settings

logger = logging.getLogger("zain.backup")

XLSX_TYPE = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT_SECONDS = 30

REJECTED_AR = "عنوان البريد مرفوض."
TOO_LARGE_AR = "حجم الملف أكبر من المسموح."
SENDER_LOGIN_AR = "تعذّر الدخول إلى حساب الإرسال. راجع كلمة مرور التطبيق."
GENERIC_AR = "تعذّر الإرسال. سنحاول في الليلة القادمة."


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    body: str
    attachment: tuple[str, bytes] | None = None


class MailError(Exception):
    """A send failed; ``reason_ar`` is what the shop owner sees."""

    def __init__(self, reason_ar: str) -> None:
        super().__init__(reason_ar)
        self.reason_ar = reason_ar


class Mailer(Protocol):
    async def send(self, message: OutgoingEmail) -> None: ...


class GmailMailer:
    def __init__(self, user: str, app_password: str) -> None:
        self._user = user
        self._password = app_password

    def _build(self, message: OutgoingEmail) -> EmailMessage:
        mail = EmailMessage()
        mail["From"] = f"ZAIN AGRI <{self._user}>"
        mail["To"] = message.to
        mail["Subject"] = message.subject
        mail.set_content(message.body)
        if message.attachment is not None:
            filename, content = message.attachment
            mail.add_attachment(
                content, maintype=XLSX_TYPE[0], subtype=XLSX_TYPE[1], filename=filename
            )
        return mail

    def _send_blocking(self, mail: EmailMessage) -> None:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.login(self._user, self._password)
            smtp.send_message(mail)

    async def send(self, message: OutgoingEmail) -> None:
        mail = self._build(message)
        try:
            await asyncio.to_thread(self._send_blocking, mail)
        except smtplib.SMTPRecipientsRefused as exc:
            raise MailError(REJECTED_AR) from exc
        except smtplib.SMTPAuthenticationError as exc:
            logger.error("backup.mail.auth_failed")
            raise MailError(SENDER_LOGIN_AR) from exc
        except smtplib.SMTPDataError as exc:
            # 552: message exceeds Gmail's size limit.
            raise MailError(TOO_LARGE_AR if exc.smtp_code == 552 else GENERIC_AR) from exc
        except smtplib.SMTPServerDisconnected as exc:
            # Gmail hangs up during AUTH when the login itself is malformed.
            logger.error("backup.mail.disconnected", extra={"error": type(exc).__name__})
            raise MailError(SENDER_LOGIN_AR) from exc
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("backup.mail.failed", extra={"error": type(exc).__name__})
            raise MailError(GENERIC_AR) from exc


def get_mailer(settings: Settings) -> Mailer | None:
    if not settings.mail_configured:
        return None
    assert settings.gmail_user is not None and settings.gmail_app_password is not None
    # Google shows app passwords as four groups with spaces, and a value pasted
    # into a terminal can carry a CR or newline. None of it is part of the
    # password, and a stray line break makes Gmail drop the SMTP login.
    password = "".join(settings.gmail_app_password.get_secret_value().split())
    return GmailMailer(settings.gmail_user.strip(), password)


def mailer_dependency() -> Mailer | None:
    return get_mailer(get_settings())


MailerDep = Annotated[Mailer | None, Depends(mailer_dependency)]
