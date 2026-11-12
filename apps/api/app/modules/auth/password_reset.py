"""Forgot password: email a single-use link, then set a new password with it.

The request step answers the same way, in about the same time, whether or not
the address has an account, so the form cannot be used to discover who is a
customer. Links are stored as SHA-256 hashes, expire after 30 minutes, work
once, and setting a password retires every other open link and every session.
"""

import asyncio
import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, UnprocessableError
from app.modules.auth import service
from app.modules.auth.models import PasswordResetToken
from app.modules.auth.schemas import check_new_password
from app.modules.backup.mailer import Mailer, MailError, OutgoingEmail
from app.modules.identity.models import User

logger = logging.getLogger("zain.security")

LINK_TTL = timedelta(minutes=30)
EMAILS_PER_HOUR = 3
# Every request takes at least this long, so a slow SMTP send for a real
# account is not distinguishable from an instant "no such account".
MIN_REQUEST_SECONDS = 3.0
INVALID_LINK = "Invalid or expired reset link"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _email(to: str, link: str) -> OutgoingEmail:
    body = (
        "طلبت تغيير كلمة المرور لحسابك في ZAIN AGRI.\n\n"
        f"افتح الرابط التالي خلال 30 دقيقة لاختيار كلمة مرور جديدة:\n\n{link}\n\n"
        "إذا لم تطلب ذلك فتجاهل هذه الرسالة، ولن يتغير شيء في حسابك."
    )
    return OutgoingEmail(to=to, subject="تغيير كلمة المرور", body=body)


async def _issue_link(
    db: AsyncSession, *, email: str, mailer: Mailer | None, settings: Settings, now: datetime
) -> None:
    user = await service.get_user_by_email(db, email)
    if user is None or not user.is_active:
        logger.info("auth.password_reset_requested", extra={"event": "reset.unknown"})
        return
    if mailer is None:
        logger.warning("auth.password_reset_requested", extra={"event": "reset.mail_off"})
        return

    recent = (
        await db.execute(
            select(func.count())
            .select_from(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at >= now - timedelta(hours=1),
            )
        )
    ).scalar_one()
    if recent >= EMAILS_PER_HOUR:
        logger.info(
            "auth.password_reset_requested",
            extra={"event": "reset.capped", "user_id": str(user.id)},
        )
        return

    token = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user.id, token_hash=_hash(token), expires_at=now + LINK_TTL, created_at=now
        )
    )
    await db.flush()
    link = f"{settings.public_app_url.rstrip('/')}/reset-password?token={token}"
    try:
        await mailer.send(_email(user.email, link))
    except MailError:
        await db.rollback()
        logger.warning(
            "auth.password_reset_requested",
            extra={"event": "reset.mail_failed", "user_id": str(user.id)},
        )
        return
    await db.commit()
    logger.info(
        "auth.password_reset_requested", extra={"event": "reset.sent", "user_id": str(user.id)}
    )


async def request_reset(
    db: AsyncSession, *, email: str, mailer: Mailer | None, settings: Settings, now: datetime
) -> None:
    """Email a reset link if the account exists. Never says whether it does."""
    started = time.monotonic()
    await _issue_link(db, email=email, mailer=mailer, settings=settings, now=now)
    remaining = MIN_REQUEST_SECONDS - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)


async def confirm_reset(db: AsyncSession, *, token: str, new_password: str, now: datetime) -> None:
    """Set the new password. The link is only spent when the password is accepted."""
    row = (
        await db.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == _hash(token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise AppError(INVALID_LINK)
    try:
        check_new_password(new_password)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc

    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AppError(INVALID_LINK)

    await service.set_password(db, user, new_password)
    # This link and every other open link for the account stop working.
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    await db.commit()
    logger.info("auth.password_reset", extra={"event": "reset.done", "user_id": str(user.id)})
