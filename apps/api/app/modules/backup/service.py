"""Backup settings: save an address, confirm it by link, stop, report status."""

import hashlib
import logging
import secrets
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AppError,
    BackupMailNotConfiguredError,
    TooManyRequestsError,
    UnprocessableError,
)
from app.modules.audit import service as audit
from app.modules.audit.models import AuditLog
from app.modules.backup.mailer import Mailer, MailError, OutgoingEmail
from app.modules.backup.models import (
    BackupDelivery,
    BackupSettings,
    BackupStatus,
    DeliveryKind,
    DeliveryStatus,
)
from app.modules.backup.schemas import BackupStatusOut
from app.modules.backup.workbook import CAIRO, cairo_date
from app.modules.identity.models import Tenant
from app.modules.tenancy.context import set_tenant_context

logger = logging.getLogger("zain.backup")

CONFIRM_TTL = timedelta(hours=24)
MANUAL_SENDS_PER_DAY = 3
INVALID_LINK = "Invalid or expired confirmation link"
TOO_MANY_LINKS = "Too many confirmation emails today"
# Confirmation emails share the Gmail quota with the backups themselves.
CONFIRM_EMAILS_PER_DAY = 5
NOT_CONFIGURED = "Backup email sending is not configured"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def load_settings(
    db: AsyncSession, tenant_id: uuid.UUID, *, for_update: bool = False
) -> BackupSettings | None:
    query = select(BackupSettings).where(BackupSettings.tenant_id == tenant_id)
    if for_update:
        # Serialises "send now" clicks so the daily cap cannot be raced past.
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def manual_sends_today(db: AsyncSession, tenant_id: uuid.UUID, today: date) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(BackupDelivery)
            .where(
                BackupDelivery.tenant_id == tenant_id,
                BackupDelivery.kind == DeliveryKind.MANUAL,
                BackupDelivery.delivery_date == today,
            )
        )
    ).scalar_one()


async def consecutive_failures(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Failed nights in a row, most recent first, stopping at the last success."""
    statuses = (
        await db.execute(
            select(BackupDelivery.status)
            .where(
                BackupDelivery.tenant_id == tenant_id,
                BackupDelivery.kind == DeliveryKind.NIGHTLY,
                BackupDelivery.status != DeliveryStatus.CLAIMED,
            )
            .order_by(BackupDelivery.delivery_date.desc())
            .limit(30)
        )
    ).scalars()
    count = 0
    for status in statuses:
        if status != DeliveryStatus.FAILED:
            break
        count += 1
    return count


async def get_status(
    db: AsyncSession, *, tenant_id: uuid.UUID, mail_configured: bool, now: datetime
) -> BackupStatusOut:
    row = await load_settings(db, tenant_id)
    last_sent_at = (
        await db.execute(
            select(func.max(BackupDelivery.updated_at)).where(
                BackupDelivery.tenant_id == tenant_id,
                BackupDelivery.status == DeliveryStatus.SENT,
            )
        )
    ).scalar_one()
    latest = (
        await db.execute(
            select(BackupDelivery)
            .where(
                BackupDelivery.tenant_id == tenant_id,
                BackupDelivery.status != DeliveryStatus.CLAIMED,
            )
            .order_by(BackupDelivery.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    used = await manual_sends_today(db, tenant_id, cairo_date(now))
    return BackupStatusOut(
        email=row.email if row else None,
        status=BackupStatus(row.status) if row else None,
        last_sent_at=last_sent_at,
        last_error_ar=(
            latest.error_reason_ar
            if latest is not None and latest.status == DeliveryStatus.FAILED
            else None
        ),
        consecutive_failures=await consecutive_failures(db, tenant_id),
        manual_sends_left=max(MANUAL_SENDS_PER_DAY - used, 0),
        mail_configured=mail_configured,
    )


def _confirmation_email(tenant: Tenant, email: str, link: str) -> OutgoingEmail:
    body = (
        f"لتأكيد استلام النسخة اليومية لمتجر «{tenant.name}» على هذا البريد، "
        f"افتح الرابط التالي خلال 24 ساعة:\n\n{link}\n\n"
        "إذا لم تطلب ذلك، تجاهل هذه الرسالة ولن يصلك شيء."
    )
    return OutgoingEmail(to=email, subject="تأكيد بريد النسخة اليومية", body=body)


async def set_address(
    db: AsyncSession,
    *,
    tenant: Tenant,
    actor_id: uuid.UUID,
    email: str,
    mailer: Mailer | None,
    settings: Settings,
    now: datetime,
) -> BackupStatusOut:
    """Store the address as pending and email a confirmation link.

    Saving the address that is already active changes nothing. Nothing is
    stored if the link email cannot be sent.
    """
    if mailer is None:
        raise BackupMailNotConfiguredError(NOT_CONFIGURED)
    row = await load_settings(db, tenant.id)
    if row is not None and row.email == email and row.status == BackupStatus.ACTIVE:
        return await get_status(db, tenant_id=tenant.id, mail_configured=True, now=now)

    day_start = now.astimezone(CAIRO).replace(hour=0, minute=0, second=0, microsecond=0)
    links_today = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.action == "backup.address_set",
                AuditLog.created_at >= day_start,
            )
        )
    ).scalar_one()
    if links_today >= CONFIRM_EMAILS_PER_DAY:
        midnight = day_start + timedelta(days=1)
        raise TooManyRequestsError(
            TOO_MANY_LINKS, retry_after=max(int((midnight - now).total_seconds()), 1)
        )

    token = secrets.token_urlsafe(32)
    if row is None:
        row = BackupSettings(tenant_id=tenant.id, email=email, status=BackupStatus.PENDING)
        db.add(row)
    row.email = email
    row.status = BackupStatus.PENDING
    row.confirm_token_hash = hash_token(token)
    row.confirm_expires_at = now + CONFIRM_TTL
    row.confirmed_at = None
    row.updated_by = actor_id
    await audit.record(
        db,
        tenant_id=tenant.id,
        actor_id=actor_id,
        action="backup.address_set",
        entity_type="backup",
        entity_id=tenant.id,
    )
    await db.flush()

    link = f"{settings.public_app_url.rstrip('/')}/backup/confirm?token={token}"
    try:
        await mailer.send(_confirmation_email(tenant, email, link))
    except MailError as exc:
        await db.rollback()
        raise UnprocessableError(exc.reason_ar) from exc
    await db.commit()
    logger.info("backup.address_set", extra={"tenant_id": str(tenant.id)})
    return await get_status(db, tenant_id=tenant.id, mail_configured=True, now=now)


async def confirm(db: AsyncSession, *, token: str, now: datetime) -> None:
    token_hash = hash_token(token)
    tenant_id = (
        await db.execute(text("SELECT app_backup_token_tenant(:h)"), {"h": token_hash})
    ).scalar_one()
    if tenant_id is None:
        raise AppError(INVALID_LINK)
    await set_tenant_context(db, tenant_id)
    row = await load_settings(db, tenant_id)
    if (
        row is None
        or row.status != BackupStatus.PENDING
        or row.confirm_token_hash != token_hash
        or row.confirm_expires_at is None
        or row.confirm_expires_at <= now
    ):
        raise AppError(INVALID_LINK)

    row.status = BackupStatus.ACTIVE
    row.confirmed_at = now
    row.confirm_token_hash = None
    row.confirm_expires_at = None
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=None,
        action="backup.confirmed",
        entity_type="backup",
        entity_id=tenant_id,
    )
    await db.commit()
    logger.info("backup.confirmed", extra={"tenant_id": str(tenant_id)})


async def stop(db: AsyncSession, *, tenant_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    row = await load_settings(db, tenant_id)
    if row is None or row.status == BackupStatus.STOPPED:
        return
    row.status = BackupStatus.STOPPED
    row.confirm_token_hash = None
    row.confirm_expires_at = None
    row.updated_by = actor_id
    await audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="backup.stopped",
        entity_type="backup",
        entity_id=tenant_id,
    )
    await db.commit()
    logger.info("backup.stopped", extra={"tenant_id": str(tenant_id)})
